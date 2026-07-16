# Private / corporate CA certificates

Build-time extension point for trusting git hosts behind a **private CA** — e.g.
a Bitbucket Data Center server whose HTTPS certificate is signed by a corporate
root that public trust stores don't know about. Without this, `git clone` from
such a host fails with `self-signed certificate in certificate chain`.

## Contract

Drop PEM-encoded certificate files here, one CA per file, with a **`.crt`**
extension:

```
certs/
  acme-root.crt
  acme-intermediate.crt   # add the intermediate too if the chain needs it
```

At `docker build` time the [`Dockerfile`](../Dockerfile) copies this directory
into `/usr/local/share/ca-certificates/okf-extra/` and runs
`update-ca-certificates`, which folds every `.crt` into the system trust bundle
(`/etc/ssl/certs/ca-certificates.crt`). That bundle is what OpenSSL — and
therefore **git** — uses, so authenticated clones over the corporate TLS path
then verify cleanly.

## Rules

- **Extension must be `.crt`, contents must be PEM.** This is the
  `update-ca-certificates` convention. A `.pem` file is silently ignored — rename
  it to `.crt`. (`.der`/binary must be converted:
  `openssl x509 -inform der -in ca.der -out ca.crt`.)
- **Nothing here is committed except this README and `.gitkeep`.** Real cert
  material is gitignored (`certs/*.crt`, `certs/*.pem`) so this reusable image
  never ships one organization's CA. Each deployer drops their own.
- **Empty is a no-op.** With only `.gitkeep` present, `update-ca-certificates`
  finds no extra certs and the image's trust store is identical to a stock
  build — public-host users need do nothing.

## Capturing a CA

If you don't already have the root as a file, you can extract the chain the
server presents and keep the CA (last cert in the chain):

```sh
openssl s_client -connect git.example.invalid:443 -showcerts </dev/null 2>/dev/null \
  | openssl x509 -outform pem > certs/example-root.crt
```

Verify it covers the host before building:

```sh
git -c http.sslCAInfo=certs/example-root.crt \
  ls-remote https://git.example.invalid/scm/~you/repo.git
```
