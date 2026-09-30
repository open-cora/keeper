"""Mint a small certificate authority and the keeper's server certificate.

    ./issue_tls.py --root /local/cora --host lyra.xray.aps.anl.gov

Run it on the host the keeper runs on. Both halves are reused if they exist,
because replacing the CA means every client has to be handed a new bundle on
the same day.

## Why a private CA rather than a public one

The keeper answers on a facility address that no public issuer can validate:
there is no inbound path from the internet, so an HTTP or DNS challenge
cannot complete. A search of this host found no internal issuing service
either. That leaves a CA of our own, which is the ordinary answer for a
service whose whole client list is known in advance and countable on one
hand.

## Why a CA and a leaf, rather than one self-signed certificate

A single self-signed certificate would have to be copied to every client as
a trusted root, so replacing the server's key means touching every client
again. With a CA in front, the server's certificate can be reissued as often
as it needs to be and the thing the clients trust never moves.

The CA's private key has no reason to be reachable once the leaf is signed.
It stays beside it here because this deployment has nowhere better yet, and
that is worth saying rather than leaving for somebody to discover.

## What this is not

Not a replacement for the token. TLS says the wire is private and the server
is the one it claims to be; the token says which beamline is calling. Each
answers a question the other cannot, and neither should grow into the
other's job.
"""

from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

CA_LIFETIME = dt.timedelta(days=3650)
LEAF_LIFETIME = dt.timedelta(days=825)
"""825 days is the longest lifetime mainstream clients accept for a leaf.

Nothing here enforces it and no browser is involved, but picking the number
the ecosystem already settled on avoids inventing a policy, and it keeps the
certificate usable if a client with opinions ever appears.
"""


def _write_private(path: Path, key: ec.EllipticCurvePrivateKey) -> None:
    path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    path.chmod(0o600)


def _load_private(path: Path) -> ec.EllipticCurvePrivateKey:
    loaded = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(loaded, ec.EllipticCurvePrivateKey):
        msg = f"{path} is not an EC private key"
        raise TypeError(msg)
    return loaded


def load_or_create_ca(
    cert_path: Path, key_path: Path
) -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    """The authority every client is asked to trust, created once."""
    if cert_path.exists() and key_path.exists():
        return x509.load_pem_x509_certificate(cert_path.read_bytes()), _load_private(key_path)

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "CORA local CA")])
    now = dt.datetime.now(dt.UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + CA_LIFETIME)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    _write_private(key_path, key)
    return certificate, key


def subject_alt_names(host: str, extra: list[str]) -> x509.SubjectAlternativeName:
    """Every name and address a client might legitimately dial.

    Loopback is included so a check run on this host needs no exception, and
    an exception made for a local check is one that tends to be copied into
    the place where it matters.
    """
    entries: list[x509.GeneralName] = [x509.DNSName(host)]
    short = host.split(".")[0]
    if short != host:
        entries.append(x509.DNSName(short))
    entries.append(x509.DNSName("localhost"))
    entries.append(x509.IPAddress(ipaddress.ip_address("127.0.0.1")))
    for value in extra:
        try:
            entries.append(x509.IPAddress(ipaddress.ip_address(value)))
        except ValueError:
            entries.append(x509.DNSName(value))
    return x509.SubjectAlternativeName(entries)


def issue_leaf(
    ca_cert: x509.Certificate,
    ca_key: ec.EllipticCurvePrivateKey,
    host: str,
    extra: list[str],
) -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    """The certificate the keeper actually presents."""
    key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + LEAF_LIFETIME)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(subject_alt_names(host, extra), critical=False)
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )
    return certificate, key


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/local/cora"))
    parser.add_argument("--host", required=True, help="the name clients will dial")
    parser.add_argument(
        "--also",
        nargs="*",
        default=[],
        help="further names or addresses to accept, such as this host's routable address",
    )
    args = parser.parse_args(argv)

    tls = args.root / "etc" / "tls"
    tls.mkdir(parents=True, exist_ok=True)
    tls.chmod(0o700)

    ca_cert_path, ca_key_path = tls / "ca.crt", tls / "ca.key"
    existed = ca_cert_path.exists()
    ca_cert, ca_key = load_or_create_ca(ca_cert_path, ca_key_path)
    print(f"ca           {ca_cert_path}  ({'reused' if existed else 'created'})")

    server_cert_path, server_key_path = tls / "server.crt", tls / "server.key"
    if server_cert_path.exists() and server_key_path.exists():
        print(f"server cert  {server_cert_path}  (reused)")
    else:
        certificate, key = issue_leaf(ca_cert, ca_key, args.host, args.also)
        server_cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        _write_private(server_key_path, key)
        expires = certificate.not_valid_after_utc.date()
        print(f"server cert  {server_cert_path}  (created, expires {expires})")

    print()
    print(f"Clients trust {ca_cert_path.name}, which goes alongside each token.")
    print("The CA key signs nothing else and never leaves this host.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
