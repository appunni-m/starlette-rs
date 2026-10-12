//! Demonstrate the server-neutral Rust WebSocket application boundary.

use std::{
    collections::VecDeque,
    error::Error,
    io,
    sync::{Arc, Mutex},
};

use bytes::Bytes;
use futures::{executor::block_on, future};
use http::{HeaderMap, Method, Request};
use http_body as _;
use http_body_util as _;
use starlette_rs::{
    NativeWebSocketAcceptance, NativeWebSocketClose, NativeWebSocketDispatch,
    NativeWebSocketDriver, NativeWebSocketError, NativeWebSocketEvent, NativeWebSocketHandshake,
    NativeWebSocketMessage, NativeWebSocketRoute, NativeWebSocketRouter,
    NativeWebSocketTransportError,
};
use tower_layer as _;
use tower_service as _;

#[derive(Default)]
struct ExampleDriver {
    offered: Mutex<VecDeque<NativeWebSocketEvent>>,
    accepted: Mutex<Option<NativeWebSocketAcceptance>>,
    sent: Mutex<Vec<NativeWebSocketMessage>>,
    close: Mutex<Option<NativeWebSocketClose>>,
}

impl NativeWebSocketDriver for ExampleDriver {
    fn accept(
        &self,
        acceptance: NativeWebSocketAcceptance,
    ) -> futures::future::BoxFuture<'_, Result<(), NativeWebSocketTransportError>> {
        let result = self
            .accepted
            .lock()
            .map_err(|_| Box::new(io::Error::other("acceptance lock poisoned")) as _)
            .map(|mut accepted| *accepted = Some(acceptance));
        Box::pin(future::ready(result))
    }

    fn receive(
        &self,
    ) -> futures::future::BoxFuture<'_, Result<NativeWebSocketEvent, NativeWebSocketTransportError>>
    {
        let result = self
            .offered
            .lock()
            .map_err(|_| Box::new(io::Error::other("message lock poisoned")) as _)
            .and_then(|mut offered| {
                offered
                    .pop_front()
                    .ok_or_else(|| Box::new(io::Error::other("no example message")) as _)
            });
        Box::pin(future::ready(result))
    }

    fn send(
        &self,
        message: NativeWebSocketMessage,
    ) -> futures::future::BoxFuture<'_, Result<(), NativeWebSocketTransportError>> {
        let result = self
            .sent
            .lock()
            .map_err(|_| Box::new(io::Error::other("sent-message lock poisoned")) as _)
            .map(|mut sent| sent.push(message));
        Box::pin(future::ready(result))
    }

    fn close(
        &self,
        close: NativeWebSocketClose,
    ) -> futures::future::BoxFuture<'_, Result<(), NativeWebSocketTransportError>> {
        let result = self
            .close
            .lock()
            .map_err(|_| Box::new(io::Error::other("close lock poisoned")) as _)
            .map(|mut stored| *stored = Some(close));
        Box::pin(future::ready(result))
    }

    fn cancelled(&self) -> futures::future::BoxFuture<'_, ()> {
        Box::pin(future::pending())
    }
}

fn main() -> Result<(), Box<dyn Error + Send + Sync>> {
    block_on(async {
        let route = NativeWebSocketRoute::new(
            "/rooms/{room_id:int}",
            ["json.v2", "chat.v1"],
            |mut session| async move {
                println!(
                    "handshake={} {}",
                    session.handshake().method(),
                    session.handshake().uri()
                );
                if let Some(session_id) = session.handshake().headers().get("x-session") {
                    println!("x-session={session_id:?}");
                }
                println!("path_params={:?}", session.path_params());
                session.accept_preferred(HeaderMap::new()).await?;
                for _ in 0..2 {
                    let NativeWebSocketEvent::Message(message) = session.receive().await? else {
                        return Err(NativeWebSocketError::application(io::Error::other(
                            "peer closed before the example finished",
                        )));
                    };
                    session.send(message).await?;
                }
                session
                    .close(NativeWebSocketClose::normal("example complete"))
                    .await
            },
        );
        let router = NativeWebSocketRouter::new([route])?;
        let request = Request::builder()
            .method(Method::GET)
            .uri("/rooms/17")
            .header("x-session", "example")
            .body(())?;
        let (parts, ()) = request.into_parts();
        let handshake = NativeWebSocketHandshake::from_parts(parts, ["chat.v1", "json.v2"]);
        let driver = Arc::new(ExampleDriver::default());
        driver
            .offered
            .lock()
            .map_err(|_| io::Error::other("message lock poisoned"))?
            .extend([
                NativeWebSocketEvent::Message(NativeWebSocketMessage::Text(String::from("hello"))),
                NativeWebSocketEvent::Message(NativeWebSocketMessage::Binary(Bytes::from_static(
                    b"payload",
                ))),
            ]);

        let result = router.dispatch(handshake, driver.clone()).await?;
        if let NativeWebSocketDispatch::Completed { route_index } = result {
            let selected_protocol = driver
                .accepted
                .lock()
                .map_err(|_| io::Error::other("acceptance lock poisoned"))?
                .as_ref()
                .and_then(NativeWebSocketAcceptance::subprotocol)
                .unwrap_or("none")
                .to_owned();
            println!("route={route_index}; subprotocol={selected_protocol}");
            println!(
                "sent={:?}",
                driver
                    .sent
                    .lock()
                    .map_err(|_| io::Error::other("sent-message lock poisoned"))?
            );
            let close = driver
                .close
                .lock()
                .map_err(|_| io::Error::other("close lock poisoned"))?;
            println!("close={:?}", close.as_ref());
        } else {
            println!("no WebSocket route matched");
        }
        Ok(())
    })
}
