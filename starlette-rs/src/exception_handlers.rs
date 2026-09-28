use std::collections::HashMap;
use std::hash::Hash;

/// Selects an exception handler by status key before matching an exception class.
///
/// Python adapters can keep their handler callables and exception objects in
/// Python while passing normalized status keys and class tokens through this
/// table. Status keys are decimal strings so Python's arbitrary-precision
/// integer keys remain representable at the boundary.
#[derive(Clone, Debug)]
pub struct ExceptionHandlerTable<ClassKey> {
    status_handlers: HashMap<String, usize>,
    class_handlers: HashMap<ClassKey, usize>,
}

impl<ClassKey> ExceptionHandlerTable<ClassKey>
where
    ClassKey: Eq + Hash,
{
    /// Creates an empty handler table.
    #[must_use]
    pub fn new() -> Self {
        Self {
            status_handlers: HashMap::new(),
            class_handlers: HashMap::new(),
        }
    }

    /// Registers the handler index for a decimal status-code key.
    pub fn insert_status(
        &mut self,
        status_key: impl Into<String>,
        handler_index: usize,
    ) -> Option<usize> {
        self.status_handlers
            .insert(status_key.into(), handler_index)
    }

    /// Registers the handler index for one exception-class token.
    pub fn insert_class(&mut self, class_key: ClassKey, handler_index: usize) -> Option<usize> {
        self.class_handlers.insert(class_key, handler_index)
    }

    /// Selects a matching status handler, then the first matching class in MRO order.
    #[must_use]
    pub fn select(&self, status_key: Option<&str>, exception_mro: &[ClassKey]) -> Option<usize> {
        if let Some(status_key) = status_key {
            if let Some(handler_index) = self.status_handlers.get(status_key) {
                return Some(*handler_index);
            }
        }

        exception_mro
            .iter()
            .find_map(|class_key| self.class_handlers.get(class_key).copied())
    }
}

impl<ClassKey> Default for ExceptionHandlerTable<ClassKey>
where
    ClassKey: Eq + Hash,
{
    fn default() -> Self {
        Self::new()
    }
}
