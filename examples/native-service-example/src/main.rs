//! Demonstrate composing the Rust-native HTTP service API with Tower.

use std::{
    collections::VecDeque,
    error::Error,
    future::Future,
    io,
    pin::Pin,
    sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    },
    task::{Context, Poll},
};

use bytes::Bytes;
use futures::{executor::block_on, future::poll_fn};
use http::{Request, Response, StatusCode, header::HeaderValue};
use http_body::{Body, Frame, SizeHint};
use http_body_util::BodyExt;
use starlette_rs::{
    NativeApplication, NativeApplicationError, NativeResponseBody, NativeRoute, box_native_body,
};
use tower_layer::Layer;
use tower_service::Service;

struct RequestIdLayer(&'static str);

struct PollObservedBody {
    frames: VecDeque<Result<Frame<Bytes>, io::Error>>,
    poll_count: Arc<AtomicUsize>,
    drop_count: Option<Arc<AtomicUsize>>,
}

impl PollObservedBody {
    fn from_chunks(chunks: impl IntoIterator<Item = Bytes>, poll_count: Arc<AtomicUsize>) -> Self {
        Self::from_chunks_with_drop(chunks, poll_count, None)
    }

    fn from_chunks_with_drop(
        chunks: impl IntoIterator<Item = Bytes>,
        poll_count: Arc<AtomicUsize>,
        drop_count: Option<Arc<AtomicUsize>>,
    ) -> Self {
        Self {
            frames: chunks
                .into_iter()
                .map(|chunk| Ok(Frame::data(chunk)))
                .collect(),
            poll_count,
            drop_count,
        }
    }
}

impl Drop for PollObservedBody {
    fn drop(&mut self) {
        if let Some(drop_count) = &self.drop_count {
            drop_count.fetch_add(1, Ordering::Relaxed);
        }
    }
}

impl Body for PollObservedBody {
    type Data = Bytes;
    type Error = io::Error;

    fn poll_frame(
        self: Pin<&mut Self>,
        _context: &mut Context<'_>,
    ) -> Poll<Option<Result<Frame<Self::Data>, Self::Error>>> {
        let this = self.get_mut();
        this.poll_count.fetch_add(1, Ordering::Relaxed);
        Poll::Ready(this.frames.pop_front())
    }

    fn is_end_stream(&self) -> bool {
        self.frames.is_empty()
    }

    fn size_hint(&self) -> SizeHint {
        SizeHint::default()
    }
}

struct RequestIdService<S> {
    inner: S,
    request_id: &'static str,
}

impl<S> Layer<S> for RequestIdLayer {
    type Service = RequestIdService<S>;

    fn layer(&self, inner: S) -> Self::Service {
        RequestIdService {
            inner,
            request_id: self.0,
        }
    }
}

impl<S, B> Service<Request<B>> for RequestIdService<S>
where
    S: Service<Request<B>>,
{
    type Response = S::Response;
    type Error = S::Error;
    type Future = S::Future;

    fn poll_ready(
        &mut self,
        context: &mut std::task::Context<'_>,
    ) -> std::task::Poll<Result<(), Self::Error>> {
        self.inner.poll_ready(context)
    }

    fn call(&mut self, mut request: Request<B>) -> Self::Future {
        request
            .headers_mut()
            .insert("x-request-id", HeaderValue::from_static(self.request_id));
        self.inner.call(request)
    }
}

fn main() -> Result<(), Box<dyn Error + Send + Sync>> {
    block_on(async_main())
}

async fn async_main() -> Result<(), Box<dyn Error + Send + Sync>> {
    let response_body_poll_count = Arc::new(AtomicUsize::new(0));
    let response_body_poll_count_for_endpoint = Arc::clone(&response_body_poll_count);
    let response_body_drop_count = Arc::new(AtomicUsize::new(0));
    let response_body_drop_count_for_endpoint = Arc::clone(&response_body_drop_count);
    let route = NativeRoute::new("/items/{item_id:int}", ["POST"], move |mut request| {
        let response_body_poll_count = Arc::clone(&response_body_poll_count_for_endpoint);
        let response_body_drop_count = Arc::clone(&response_body_drop_count_for_endpoint);
        async move {
            let mut request_bytes = Vec::new();
            while let Some(frame) = request.body_mut().frame().await {
                let frame = frame.map_err(NativeApplicationError::Endpoint)?;
                if let Ok(data) = frame.into_data() {
                    request_bytes.extend_from_slice(&data);
                }
            }

            let item_id = request
                .path_params()
                .iter()
                .find(|(name, _)| name == "item_id")
                .map(|(_, value)| value.as_str())
                .ok_or_else(|| {
                    NativeApplicationError::Endpoint(Box::new(io::Error::other(
                        "route did not provide item_id",
                    )))
                })?;
            let query = request.query().unwrap_or_default();
            let request_id = request
                .headers()
                .get("x-request-id")
                .and_then(|value| value.to_str().ok())
                .unwrap_or("missing");
            let response_chunks = [
                Bytes::from(format!(
                    "id={item_id};query={query};request={request_id};body="
                )),
                Bytes::from(request_bytes),
            ];
            let body: NativeResponseBody =
                box_native_body(PollObservedBody::from_chunks_with_drop(
                    response_chunks,
                    response_body_poll_count,
                    Some(response_body_drop_count),
                ));
            Response::builder()
                .status(StatusCode::OK)
                .header("x-native-route", HeaderValue::from_static("matched"))
                .body(body)
                .map_err(|error| NativeApplicationError::Endpoint(Box::new(error)))
        }
    });

    let native_application = NativeApplication::new([route])?;
    type NativeService = RequestIdService<NativeApplication>;
    let mut application: NativeService =
        RequestIdLayer("example-request").layer(native_application);

    let request_body_poll_count = Arc::new(AtomicUsize::new(0));
    let request_body = PollObservedBody::from_chunks(
        [Bytes::from_static(b"hel"), Bytes::from_static(b"lo")],
        Arc::clone(&request_body_poll_count),
    );
    let request = Request::builder()
        .method("POST")
        .uri("/items/7?lang=en")
        .body(request_body)?;

    poll_fn(|context| {
        <NativeService as Service<Request<PollObservedBody>>>::poll_ready(&mut application, context)
    })
    .await?;
    let response_future =
        <NativeService as Service<Request<PollObservedBody>>>::call(&mut application, request);
    println!(
        "Request body polls before the endpoint future runs: {}",
        request_body_poll_count.load(Ordering::Relaxed)
    );
    let response = response_future.await?;
    println!("HTTP {}", response.status());
    println!(
        "x-native-route: {:?}",
        response.headers().get("x-native-route")
    );
    let mut response_body = response.into_body();
    println!(
        "Response body polls before the consumer asks for a frame: {}",
        response_body_poll_count.load(Ordering::Relaxed)
    );
    print!("Body: ");
    while let Some(frame) = response_body.frame().await {
        let frame = frame?;
        if let Ok(data) = frame.into_data() {
            print!("{}", String::from_utf8_lossy(&data));
        }
    }
    println!();
    println!(
        "Response body poll attempts after consumption: {}",
        response_body_poll_count.load(Ordering::Relaxed)
    );
    drop(response_body);
    println!(
        "Response-body source drops after the consumer drops it: {}",
        response_body_drop_count.load(Ordering::Relaxed)
    );

    let cancelled_request_body_poll_count = Arc::new(AtomicUsize::new(0));
    let cancelled_request_body_drop_count = Arc::new(AtomicUsize::new(0));
    let pending_route = NativeRoute::new("/pending", ["POST"], |request| async move {
        let result =
            std::future::pending::<Result<Response<NativeResponseBody>, NativeApplicationError>>()
                .await;
        drop(request);
        result
    });
    let mut pending_application = NativeApplication::new([pending_route])?;
    let pending_request_body = PollObservedBody::from_chunks_with_drop(
        [Bytes::from_static(b"not consumed")],
        Arc::clone(&cancelled_request_body_poll_count),
        Some(Arc::clone(&cancelled_request_body_drop_count)),
    );
    let pending_request = Request::builder()
        .method("POST")
        .uri("/pending")
        .body(pending_request_body)?;
    let mut pending_future = Box::pin(pending_application.call(pending_request));
    let first_poll = poll_fn(|context| Poll::Ready(pending_future.as_mut().poll(context))).await;
    let first_poll_state = match first_poll {
        Poll::Pending => "pending",
        Poll::Ready(Ok(_)) => "ready with response",
        Poll::Ready(Err(_)) => "ready with error",
    };
    println!("Pending endpoint first poll: {first_poll_state}");
    drop(pending_future);
    println!(
        "Request-body polls before cancellation: {}",
        cancelled_request_body_poll_count.load(Ordering::Relaxed)
    );
    println!(
        "Request-body source drops after cancelling the pending future: {}",
        cancelled_request_body_drop_count.load(Ordering::Relaxed)
    );
    Ok(())
}
