//! Shows a host driving the runtime-agnostic lifecycle API on its own executor.

use std::error::Error;

use starlette_rs::{NativeLifespan, NativeLifespanStateError};

#[derive(Debug)]
struct DatabasePool {
    connection_limit: usize,
}

fn main() -> Result<(), Box<dyn Error>> {
    let lifecycle = NativeLifespan::builder()
        .on_lifecycle(
            |state| async move {
                state.insert(
                    "database",
                    DatabasePool {
                        connection_limit: 8,
                    },
                )
            },
            |state| async move {
                let _pool = state.remove::<DatabasePool>("database")?;
                Ok::<(), NativeLifespanStateError>(())
            },
        )
        .build();

    // This host drives both futures to completion. A production host can apply
    // its own deadline, but dropping a future does not start async cleanup or
    // preserve shutdown progress for a retry.
    let active = futures::executor::block_on(lifecycle.start())?;
    let pool = active
        .state()
        .get::<DatabasePool>("database")?
        .ok_or("startup did not insert the database pool")?;
    println!("database pool limit: {}", pool.connection_limit);
    futures::executor::block_on(active.shutdown())?;
    println!(
        "retained pool limit after shutdown: {}",
        pool.connection_limit
    );
    Ok(())
}
