# Retired parity inputs

`endpoints-runtime.yaml` is preserved verbatim from its former location at
`tests/fixtures/sources/parity/endpoints-runtime.yaml`. It was an unindexed
input draft, so it is not part of the active parity contract and must not be
used as parity evidence. The generator indexes only YAML sources under
`../parity/` and `../benchmark/`.

Its cases use the retired `class-based-endpoint` operation and requirement
names that are not declared by the current manifest. The maintained endpoint
workflows are now in `../parity/router-class-based-endpoints.yaml`,
`../parity/http-endpoint-dispatch.yaml`, and
`../parity/websocket-endpoint-dispatch.yaml`. To revive any scenario, express it
using the current public operation and requirements, index it in
`tests/fixtures/manifest.yaml`, and validate it with `make contract-check`.
