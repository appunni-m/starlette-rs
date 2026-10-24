use std::collections::VecDeque;
use std::error::Error;
use std::pin::Pin;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::task::{Context, Poll};

use futures::Stream;
use serde_json::{Map, Value, json};
use starlette_rs::{
    StreamingResponseCall, StreamingResponseCallError, StreamingResponseCallInput,
    StreamingResponseDisconnectCall, StreamingResponseDisconnectCallInput,
    StreamingResponseDisconnectCallStep, StreamingResponseDisconnectListener,
    StreamingResponseDisconnectListenerInput, StreamingResponseDisconnectListenerStep,
    StreamingResponseDisconnectMessage, StreamingResponseEvent,
};

use super::{canonical_headers, encode_base64};

#[derive(Debug)]
pub(super) struct NativeStreamProducerError {
    pub(super) class: String,
    pub(super) message: String,
}

impl std::fmt::Display for NativeStreamProducerError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl Error for NativeStreamProducerError {}

#[derive(Clone, Copy)]
pub(super) enum NativeStreamTerminal {
    End,
    Error,
}

pub(super) struct NativeSourceProbe {
    pub(super) items: VecDeque<Vec<u8>>,
    pub(super) pull_markers: Vec<String>,
    pub(super) next_marker: usize,
    pub(super) terminal: NativeStreamTerminal,
    pub(super) producer_error: Option<NativeStreamProducerError>,
    pub(super) terminal_sent: bool,
    pub(super) finally_marker: String,
    pub(super) poll_trace: Arc<Mutex<Vec<String>>>,
    pub(super) execution_trace: Arc<Mutex<Vec<String>>>,
    pub(super) finalized: Arc<AtomicBool>,
}

impl Stream for NativeSourceProbe {
    type Item = Result<Vec<u8>, NativeStreamProducerError>;

    fn poll_next(mut self: Pin<&mut Self>, _context: &mut Context<'_>) -> Poll<Option<Self::Item>> {
        if let Some(item) = self.items.pop_front() {
            let marker = self.pull_markers.get(self.next_marker).cloned();
            let Some(next_marker) = self.next_marker.checked_add(1) else {
                return Poll::Ready(Some(Err(NativeStreamProducerError {
                    class: String::from("OverflowError"),
                    message: String::from("stream source marker index overflow"),
                })));
            };
            self.next_marker = next_marker;
            if let Some(marker) = marker {
                if let Ok(mut trace) = self.poll_trace.lock() {
                    trace.push(marker.clone());
                }
                if let Ok(mut trace) = self.execution_trace.lock() {
                    trace.push(format!("source:{marker}"));
                }
            }
            return Poll::Ready(Some(Ok(item)));
        }
        if !self.terminal_sent {
            self.terminal_sent = true;
            if let NativeStreamTerminal::Error = self.terminal {
                return Poll::Ready(self.producer_error.take().map(Err));
            }
        }
        Poll::Ready(None)
    }
}

impl Drop for NativeSourceProbe {
    fn drop(&mut self) {
        if !self.finalized.swap(true, Ordering::AcqRel) {
            if let Ok(mut trace) = self.poll_trace.lock() {
                trace.push(format!("source-finalize:{}", self.finally_marker));
            }
        }
    }
}

pub(super) fn native_stream_record_finalization(
    finalized: &AtomicBool,
    execution_finalized: &mut bool,
    finally_marker: &str,
    execution_trace: &Arc<Mutex<Vec<String>>>,
) {
    if finalized.load(Ordering::Acquire) && !*execution_finalized {
        if let Ok(mut trace) = execution_trace.lock() {
            trace.push(format!("source-finalize:{finally_marker}"));
        }
        *execution_finalized = true;
    }
}

pub(super) fn native_stream_event(event: StreamingResponseEvent) -> Value {
    match event {
        StreamingResponseEvent::Start {
            status_code,
            headers,
        } => json!({
            "type": "http.response.start",
            "status": status_code,
            "headers_base64_pairs": canonical_headers(&headers),
        }),
        StreamingResponseEvent::Body { body, more_body } => json!({
            "type": "http.response.body",
            "body_base64": encode_base64(&body),
            "more_body": more_body,
        }),
    }
}

pub(super) fn native_stream_has_disconnect_input(
    case: &Map<String, Value>,
) -> Result<bool, String> {
    let incoming = case
        .get("incoming")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("native streaming source incoming must be an array"))?;
    let has_disconnect = incoming
        .iter()
        .any(|message| message.get("type").and_then(Value::as_str) == Some("http.disconnect"));
    if has_disconnect {
        let send = case
            .get("send")
            .and_then(Value::as_object)
            .ok_or_else(|| String::from("native streaming source send must be an object"))?;
        let event_index = send.get("event_index").and_then(Value::as_u64);
        let is_scheduled = send.get("kind").and_then(Value::as_str)
            == Some("capture-asgi-send-with-checkpoint-gate")
            && event_index.is_some_and(|event_index| {
                incoming.iter().any(|message| {
                    message.get("type").and_then(Value::as_str) == Some("http.disconnect")
                        && message.get("after_send_index").and_then(Value::as_u64)
                            == Some(event_index)
                })
            });
        if !is_scheduled {
            return Err(String::from(
                "native streaming disconnect must be scheduled at a gated send event",
            ));
        }
    }
    Ok(has_disconnect)
}

fn native_stream_disconnect_call_for_send(
    case: &Map<String, Value>,
    sent_index: u64,
    stream_call: &mut StreamingResponseCall,
) -> Result<Option<StreamingResponseDisconnectCall<NativeStreamProducerError>>, String> {
    let send = case
        .get("send")
        .and_then(Value::as_object)
        .ok_or_else(|| String::from("native streaming source send must be an object"))?;
    if send.get("kind").and_then(Value::as_str) != Some("capture-asgi-send-with-checkpoint-gate")
        || send.get("event_index").and_then(Value::as_u64) != Some(sent_index)
    {
        return Ok(None);
    }
    let incoming = case
        .get("incoming")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("native streaming source incoming must be an array"))?;
    let scheduled: Vec<_> = incoming
        .iter()
        .filter(|message| {
            message.get("after_send_index").and_then(Value::as_u64) == Some(sent_index)
        })
        .collect();
    if !scheduled
        .iter()
        .any(|message| message.get("type").and_then(Value::as_str) == Some("http.disconnect"))
    {
        return Ok(None);
    }

    let mut listener = StreamingResponseDisconnectListener::new();
    let has_background_callback = case
        .get("background")
        .is_some_and(|background| !background.is_null());
    let mut disconnect_call = StreamingResponseDisconnectCall::new(has_background_callback);
    disconnect_call
        .advance(StreamingResponseDisconnectCallInput::ConcurrentStarted)
        .map_err(|error| format!("native streaming disconnect start failed: {error:?}"))?;
    let mut disconnected = false;
    for message in scheduled {
        let message_type = message
            .get("type")
            .and_then(Value::as_str)
            .ok_or_else(|| String::from("native streaming incoming type must be a string"))?;
        let received = match message_type {
            "http.disconnect" => StreamingResponseDisconnectMessage::Disconnect,
            "http.request" => StreamingResponseDisconnectMessage::Other,
            _ => {
                return Err(format!(
                    "native streaming incoming type is unsupported: {message_type}"
                ));
            }
        };
        disconnected = listener
            .advance(StreamingResponseDisconnectListenerInput::<
                NativeStreamProducerError,
            >::Received(received))
            .map_err(|error| format!("native streaming disconnect receive failed: {error:?}"))?
            == StreamingResponseDisconnectListenerStep::Complete;
        if disconnected {
            break;
        }
    }
    if !disconnected {
        return Err(String::from(
            "native streaming disconnect gate did not provide http.disconnect",
        ));
    }
    disconnect_call
        .advance(StreamingResponseDisconnectCallInput::ListenerFinished(Ok(
            (),
        )))
        .map_err(|error| format!("native streaming disconnect listener failed: {error:?}"))?;
    match stream_call.advance(StreamingResponseCallInput::Send(Err(
        NativeStreamProducerError {
            class: String::from("CancelledError"),
            message: String::new(),
        },
    ))) {
        Err(StreamingResponseCallError::Operation(error)) if error.class == "CancelledError" => {}
        Err(error) => return Err(format!("native streaming cancellation failed: {error:?}")),
        Ok(_) => {
            return Err(String::from(
                "native streaming cancellation did not stop the stream",
            ));
        }
    }
    disconnect_call
        .advance(StreamingResponseDisconnectCallInput::StreamFinished(Ok(())))
        .map_err(|error| format!("native streaming cancellation cleanup failed: {error:?}"))?;
    disconnect_call
        .advance(StreamingResponseDisconnectCallInput::ConcurrentFinished(
            Ok(()),
        ))
        .map_err(|error| format!("native streaming disconnect race failed: {error:?}"))?;
    Ok(Some(disconnect_call))
}

fn native_stream_finish_disconnect_background(
    disconnect_call: &mut StreamingResponseDisconnectCall<NativeStreamProducerError>,
    background_values: &[String],
    background_error: Option<&NativeStreamProducerError>,
    execution_trace: &Arc<Mutex<Vec<String>>>,
    background_execution_trace: &mut Vec<String>,
    error: &mut Value,
) -> Result<(), String> {
    if disconnect_call.step() != StreamingResponseDisconnectCallStep::RunBackground {
        return Ok(());
    }
    for value in background_values {
        if let Ok(mut trace) = execution_trace.lock() {
            trace.push(format!("background:{value}"));
        }
        background_execution_trace.push(value.clone());
    }
    let background_result = match background_error {
        Some(background_error) => {
            *error = json!({
                "class": background_error.class,
                "message": background_error.message,
            });
            Err(NativeStreamProducerError {
                class: background_error.class.clone(),
                message: background_error.message.clone(),
            })
        }
        None => Ok(()),
    };
    disconnect_call
        .advance(StreamingResponseDisconnectCallInput::BackgroundFinished(
            background_result,
        ))
        .map_err(|error| format!("native streaming background callback failed: {error:?}"))?;
    Ok(())
}

pub(super) struct NativeStreamDisconnectBackground<'a> {
    pub(super) values: &'a [String],
    pub(super) failure: Option<&'a NativeStreamProducerError>,
    pub(super) execution_trace: &'a Arc<Mutex<Vec<String>>>,
    pub(super) executed: &'a mut Vec<String>,
    pub(super) error: &'a mut Value,
}

pub(super) fn native_stream_disconnect_before_send(
    case: &Map<String, Value>,
    sent_index: u64,
    stream_call: &mut StreamingResponseCall,
    background: NativeStreamDisconnectBackground<'_>,
) -> Result<bool, String> {
    let Some(mut disconnect_call) =
        native_stream_disconnect_call_for_send(case, sent_index, stream_call)?
    else {
        return Ok(false);
    };
    native_stream_finish_disconnect_background(
        &mut disconnect_call,
        background.values,
        background.failure,
        background.execution_trace,
        background.executed,
        background.error,
    )?;
    Ok(true)
}

pub(super) fn native_stream_cancel_call(
    call: &mut StreamingResponseCall,
    execution_trace: &Arc<Mutex<Vec<String>>>,
    error: &mut Value,
) {
    if let Ok(mut trace) = execution_trace.lock() {
        trace.push(String::from("send:cancel"));
    }
    let cancellation = NativeStreamProducerError {
        class: String::from("CancelledError"),
        message: String::new(),
    };
    let _ = call
        .advance(StreamingResponseCallInput::<NativeStreamProducerError>::Send(Err(cancellation)));
    *error = json!({"class": "CancelledError", "message": ""});
}
