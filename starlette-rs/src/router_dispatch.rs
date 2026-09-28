//! Ordered HTTP dispatch planning on top of [`RouteTable`].

use std::error::Error;
use std::fmt::{self, Display, Formatter};

use crate::{DetailedRouteMatch, RouteTable};

/// The route-level action an HTTP router should take for a request.
///
/// A redirect contains the alternate full ASGI scope path. The caller remains
/// responsible for constructing a redirect response with the request's scheme,
/// authority, and query string.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum HttpDispatchPlan {
    /// A route accepted both the path and method.
    Matched {
        /// Zero-based insertion index of the selected route.
        route_index: usize,
        /// Converted parameters captured from the request path.
        path_params: Vec<(String, String)>,
    },
    /// A route accepted the path, but no matching route accepted the method.
    MethodNotAllowed {
        /// Zero-based insertion index of the first path-only match.
        route_index: usize,
        /// Methods registered on the selected path match.
        allowed_methods: Vec<String>,
        /// Converted parameters captured from the request path.
        path_params: Vec<(String, String)>,
    },
    /// No route matched the request path, but a trailing-slash alternative did.
    Redirect {
        /// Alternate full ASGI scope path, including any `root_path` prefix.
        path: String,
    },
    /// Neither the request path nor its trailing-slash alternative matched.
    NotFound,
}

/// A full or partial match supplied by a route adapter outside the native
/// [`RouteTable`], such as a Python route with a registered custom converter.
///
/// The route index is its position in the router's complete declaration
/// order. Path parameters are intentionally omitted: the route adapter keeps
/// its converted child scope and applies it only if this candidate is chosen.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SupplementalRouteMatch {
    /// An adapter accepted the path and method.
    Matched {
        /// Zero-based index in the router's complete route list.
        route_index: usize,
    },
    /// An adapter accepted the path but not the method.
    MethodNotAllowed {
        /// Zero-based index in the router's complete route list.
        route_index: usize,
        /// Methods accepted by the route.
        allowed_methods: Vec<String>,
    },
}

/// An invalid mapping from native-table indexes to router declaration indexes.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum DispatchPlanError {
    /// There must be one router index for every entry in the native table.
    RouteIndexCountMismatch {
        /// Number of routes in the native table.
        table_route_count: usize,
        /// Number of supplied router indexes.
        router_index_count: usize,
    },
}

impl Display for DispatchPlanError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        match self {
            Self::RouteIndexCountMismatch {
                table_route_count,
                router_index_count,
            } => write!(
                formatter,
                "native route table has {table_route_count} entries but router index map has {router_index_count}"
            ),
        }
    }
}

impl Error for DispatchPlanError {}

impl RouteTable {
    /// Plans the HTTP router action for a path, method, and ASGI `root_path`.
    ///
    /// The current path is matched first. A full match or method-only partial
    /// match is returned immediately; trailing-slash redirect lookup occurs
    /// only after the current path is a miss. This preserves Starlette router
    /// precedence, where an existing partial match wins before redirect
    /// selection. Matching and redirect candidate selection both delegate to
    /// this table's existing route decisions and built-in converters.
    ///
    /// `path` is the full ASGI scope path. A redirect plan carries the
    /// alternate full scope path; callers can combine it with scope URL fields
    /// to construct a redirect response.
    #[must_use]
    pub fn dispatch_plan(&self, path: &str, root_path: &str, method: &str) -> HttpDispatchPlan {
        match self.matches_detailed_with_root_path(path, root_path, method) {
            DetailedRouteMatch::Matched {
                route_index,
                path_params,
            } => HttpDispatchPlan::Matched {
                route_index,
                path_params,
            },
            DetailedRouteMatch::MethodNotAllowed {
                route_index,
                allowed_methods,
                path_params,
            } => HttpDispatchPlan::MethodNotAllowed {
                route_index,
                allowed_methods,
                path_params,
            },
            DetailedRouteMatch::NotFound => self
                .find_slash_redirect_path(path, root_path, method)
                .map_or(HttpDispatchPlan::NotFound, |path| {
                    HttpDispatchPlan::Redirect { path }
                }),
        }
    }

    /// Plans dispatch while merging route matches supplied by a route adapter.
    ///
    /// `router_route_indexes` maps each local native-table index to its
    /// position in the router's complete declaration order. The callback
    /// evaluates routes that require a non-native matcher and returns their
    /// FULL or PARTIAL candidates for the full ASGI path it receives. The
    /// callback also receives the declaration index of a native FULL match,
    /// when present, so adapters can avoid invoking later Python matchers that
    /// Starlette's ordered dispatch would never reach.
    /// This method owns global ordering: the earliest FULL match wins; if
    /// there is none, the earliest PARTIAL match wins. It computes the
    /// root-path-aware slash alternative only after both native and
    /// supplemental matching report no match. Set `redirect_slashes` to false
    /// for a protocol such as WebSocket routing that does not redirect.
    ///
    /// Supplemental routes retain their language-specific child scopes in the
    /// callback/adapter. Their `path_params` are therefore empty in the
    /// returned plan; native-table matches return the table's captured values.
    ///
    /// # Errors
    ///
    /// Returns [`DispatchPlanError::RouteIndexCountMismatch`] if the index map
    /// does not contain exactly one entry for every native-table route.
    pub fn dispatch_plan_with_candidates<F>(
        &self,
        path: &str,
        root_path: &str,
        method: &str,
        router_route_indexes: &[usize],
        redirect_slashes: bool,
        mut supplemental_matches: F,
    ) -> Result<HttpDispatchPlan, DispatchPlanError>
    where
        F: FnMut(&str, Option<usize>) -> Vec<SupplementalRouteMatch>,
    {
        if router_route_indexes.len() != self.len() {
            return Err(DispatchPlanError::RouteIndexCountMismatch {
                table_route_count: self.len(),
                router_index_count: router_route_indexes.len(),
            });
        }

        let current = self.matches_detailed_with_root_path(path, root_path, method);
        let current_full_index = native_full_route_index(&current, router_route_indexes);
        let current_supplemental = supplemental_matches(path, current_full_index);
        let selected = combine_route_matches(current, router_route_indexes, current_supplemental);
        if selected != HttpDispatchPlan::NotFound {
            return Ok(selected);
        }

        if !redirect_slashes {
            return Ok(HttpDispatchPlan::NotFound);
        }
        let Some(candidate_path) = self.slash_redirect_candidate(path, root_path) else {
            return Ok(HttpDispatchPlan::NotFound);
        };

        let candidate_native =
            self.matches_detailed_with_root_path(&candidate_path, root_path, method);
        let candidate_full_index = native_full_route_index(&candidate_native, router_route_indexes);
        let candidate_supplemental = supplemental_matches(&candidate_path, candidate_full_index);
        let candidate = combine_route_matches(
            candidate_native,
            router_route_indexes,
            candidate_supplemental,
        );
        match candidate {
            HttpDispatchPlan::NotFound | HttpDispatchPlan::Redirect { .. } => {
                Ok(HttpDispatchPlan::NotFound)
            }
            HttpDispatchPlan::Matched { .. } | HttpDispatchPlan::MethodNotAllowed { .. } => {
                Ok(HttpDispatchPlan::Redirect {
                    path: candidate_path,
                })
            }
        }
    }

    /// Produces the alternate full ASGI path for Starlette's slash redirect,
    /// without checking whether any route accepts that path.
    #[must_use]
    pub fn slash_redirect_candidate(&self, path: &str, root_path: &str) -> Option<String> {
        let route_path = crate::route_table::get_route_path(path, root_path);
        if route_path == "/" {
            return None;
        }

        Some(if route_path.ends_with('/') {
            path.trim_end_matches('/').to_owned()
        } else {
            format!("{path}/")
        })
    }
}

fn native_full_route_index(
    native: &DetailedRouteMatch,
    router_route_indexes: &[usize],
) -> Option<usize> {
    match native {
        DetailedRouteMatch::Matched { route_index, .. } => Some(router_route_indexes[*route_index]),
        DetailedRouteMatch::MethodNotAllowed { .. } | DetailedRouteMatch::NotFound => None,
    }
}

fn combine_route_matches(
    native: DetailedRouteMatch,
    router_route_indexes: &[usize],
    supplemental: Vec<SupplementalRouteMatch>,
) -> HttpDispatchPlan {
    let (native_full, native_partial) = match native {
        DetailedRouteMatch::Matched {
            route_index,
            path_params,
        } => (Some((router_route_indexes[route_index], path_params)), None),
        DetailedRouteMatch::MethodNotAllowed {
            route_index,
            allowed_methods,
            path_params,
        } => (
            None,
            Some((
                router_route_indexes[route_index],
                allowed_methods,
                path_params,
            )),
        ),
        DetailedRouteMatch::NotFound => (None, None),
    };

    let supplemental_full = supplemental
        .iter()
        .filter_map(|candidate| match candidate {
            SupplementalRouteMatch::Matched { route_index } => Some(*route_index),
            SupplementalRouteMatch::MethodNotAllowed { .. } => None,
        })
        .min();
    if let Some((native_index, native_params)) = native_full {
        if supplemental_full.is_none_or(|supplemental_index| native_index <= supplemental_index) {
            return HttpDispatchPlan::Matched {
                route_index: native_index,
                path_params: native_params,
            };
        }
    }
    if let Some(route_index) = supplemental_full {
        return HttpDispatchPlan::Matched {
            route_index,
            path_params: Vec::new(),
        };
    }

    let supplemental_partial = supplemental
        .into_iter()
        .filter_map(|candidate| match candidate {
            SupplementalRouteMatch::Matched { .. } => None,
            SupplementalRouteMatch::MethodNotAllowed {
                route_index,
                allowed_methods,
            } => Some((route_index, allowed_methods)),
        })
        .min_by_key(|(route_index, _)| *route_index);

    match (native_partial, supplemental_partial) {
        (Some((native_index, allowed_methods, path_params)), Some((supplemental_index, _)))
            if native_index <= supplemental_index =>
        {
            HttpDispatchPlan::MethodNotAllowed {
                route_index: native_index,
                allowed_methods,
                path_params,
            }
        }
        (Some((route_index, allowed_methods, path_params)), None) => {
            HttpDispatchPlan::MethodNotAllowed {
                route_index,
                allowed_methods,
                path_params,
            }
        }
        (_, Some((route_index, allowed_methods))) => HttpDispatchPlan::MethodNotAllowed {
            route_index,
            allowed_methods,
            path_params: Vec::new(),
        },
        (None, None) => HttpDispatchPlan::NotFound,
    }
}
