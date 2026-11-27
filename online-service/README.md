# Wondershot room service

This Cloudflare Worker handles room discovery, admission and WebRTC signaling. It does not run the game. Gameplay travels directly between peers or through Cloudflare TURN, using encrypted WebRTC data channels.

## Deployment

Run `npm ci` and `npm test`. Authenticate Wrangler to your own Cloudflare account. Set `TURN_KEY_ID` and `TURN_API_TOKEN` with `wrangler secret put` using interactive input; never put the values in source or a client. A private deployment additionally sets `TEST_ACCESS_KEY`. The committed configuration omits account identifiers and secret values and defaults to private operation. Only explicitly set `PRIVATE_TEST` to `"false"` after validating admission and service limits.

The official client uses the Wondershot service URL in `host/wonder_online/transport.cpp`. Self-hosters can set `WONDER_ONLINE_SERVICE` to their own HTTPS endpoint. Plain HTTP is accepted only for localhost development. Released clients need no Cloudflare account, private access file or administrator key.

## Limits and privacy

The initial service limits are 50 room creations and 100 TURN credential issuances per UTC day, enforced by one durable budget. Per-location admission limiting is 6 attempts per minute per hashed network address; general traffic is limited separately. Room admission also limits failed attempts. Reaching a limit denies requests rather than increasing it automatically. These application limits are not a billing guarantee or a strict cap on all bandwidth that already-issued TURN credentials can use. Do not enable a paid plan or billing without the operator's explicit decision.

Rooms support one host and one guest. Admission checks a salted hash of the game's security configuration before issuing guest capabilities. Guest departure rotates its bearer token and signaling generation. Heartbeats remove stale guests and hosts; room credentials expire after six hours. Directory advertisements expire independently and omit guest names and unused node/padding data.

Permanent TURN keys remain Worker secrets. Clients necessarily receive temporary TURN credentials and their own session bearer token. Profiles retain a random network identity locally; the service receives its fingerprint for duplicate-player detection, not a Nintendo identity. Names are user-chosen public room data. Peer IP addresses are visible in Direct preferred mode; Private relay filters direct candidates. Cloudflare necessarily processes connection metadata. Production request-body and raw signaling logs must remain disabled; error responses contain no credentials or submitted payloads.

Use `npm test` for runtime tests. Local development can run `wrangler dev --ip 127.0.0.1 --var PRIVATE_TEST:false --var TURN_ENABLED:false` for direct connectivity without any production secrets.
