//! Demonstrate composing the additive HTTP service API with Tower.

use std::{error::Error, io};

use bytes::Bytes;
use futures::{executor::block_on, future::poll_fn, stream};
use http::{Request, Response, StatusCode, header::HeaderValue};
use http_body_util::{BodyExt, Full, StreamBody};
use starlette_rs::{
    NativeApplication, NativeApplicationError, NativeResponseBody, NativeRoute, box_native_body,
};
use tower_layer::Layer;
use tower_service::Service;

struct RequestIdLayer(&'static str);

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
    let route = NativeRoute::new("/items/{item_id:int}", ["POST"], |mut request| async move {
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
        let response_stream = stream::iter(
            response_chunks
                .into_iter()
                .map(|chunk| Ok::<_, io::Error>(http_body::Frame::data(chunk))),
        );
        let body: NativeResponseBody = box_native_body(StreamBody::new(response_stream));
        Response::builder()
            .status(StatusCode::OK)
            .header("x-native-route", HeaderValue::from_static("matched"))
            .body(body)
            .map_err(|error| NativeApplicationError::Endpoint(Box::new(error)))
    });

    let native_application = NativeApplication::new([route])?;
    type NativeService = RequestIdService<NativeApplication>;
    let mut application: NativeService =
        RequestIdLayer("example-request").layer(native_application);
    let request = Request::builder()
        .method("POST")
        .uri("/items/7?lang=en")
        .body(Full::new(Bytes::from_static(b"hello")))?;

    poll_fn(|context| {
        <NativeService as Service<Request<Full<Bytes>>>>::poll_ready(&mut application, context)
    })
    .await?;
    let response =
        <NativeService as Service<Request<Full<Bytes>>>>::call(&mut application, request).await?;
    println!("HTTP {}", response.status());
    println!(
        "x-native-route: {:?}",
        response.headers().get("x-native-route")
    );
    print!("Body: ");
    let mut response_body = response.into_body();
    while let Some(frame) = response_body.frame().await {
        let frame = frame?;
        if let Ok(data) = frame.into_data() {
            print!("{}", String::from_utf8_lossy(&data));
        }
    }
    println!();
    Ok(())
}
