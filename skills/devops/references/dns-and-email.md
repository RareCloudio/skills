# DNS and email

Read this when an app needs DNS records created or changed, a move between servers needs the
records switched without an outage, a name resolves to the wrong place, or the app has to send
mail that arrives. The proxy and its certificates are in [web-and-https.md](web-and-https.md);
the outside check and the hand-over are in [proving-it-works.md](proving-it-works.md). Running a
mail server to receive mail is out of scope: point MX at a hosted mailbox service.

## Find where the records live first

Records are served by whichever DNS host the domain's NS records name, which is often not the
registrar. A record added in the wrong panel is simply ignored. `dig +short NS example.com`
names the servers; that is where changes go.

A change to a live domain needs the person's yes, with the record named. A wrong A record takes
the site down and a wrong MX loses mail, in both cases for as long as resolvers cache it. Before
changing anything, save the current records (the DNS host's export, or a `dig` of each name you
will touch) so the way back is a paste.

## The records an app needs

Verified with `named-checkzone` and served from a local BIND (zone-file syntax; a web panel asks
for the same fields, usually with the name relative to the domain, `app` or `@`):

```
app.example.com.          300  IN A      203.0.113.10
app.example.com.          300  IN AAAA   2001:db8::10
www.example.com.          300  IN CNAME  app.example.com.
example.com.             3600  IN CAA    0 issue "letsencrypt.org"
example.com.             3600  IN CAA    0 issuewild ";"
example.com.             3600  IN TXT    "v=spf1 include:spf.mail-sender.example -all"
s1._domainkey.example.com. 3600 IN CNAME s1.dkim.mail-sender.example.
_dmarc.example.com.      3600  IN TXT    "v=DMARC1; p=none; rua=mailto:<REPORT_ADDRESS>"
```

- **A and AAAA** map a name to the server's IPv4 and IPv6 address. Add the AAAA only when the
  app answers on that IPv6 address (see the trap below).
- **CNAME** makes a name an alias of another name. It cannot share its name with any other
  record: BIND refuses the zone with `CNAME and other data`, and DNS hosts refuse or misbehave.
- **The apex problem.** `example.com` itself always carries SOA and NS records, so it cannot be
  a CNAME. Use A and AAAA records there, or the DNS host's alias feature (called ALIAS, ANAME
  or CNAME flattening; it answers with the target's addresses), or serve the app on `www` and
  redirect the bare name to it.
- **CAA** lists the certificate authorities allowed to issue for the domain and its subdomains.
  Without one, any may. With one, the CA your proxy uses has to be on it, or issuance fails
  with a CAA error. Caddy falls back to ZeroSSL when Let's Encrypt fails, and ZeroSSL's own help
  pages say it needs `0 issue "sectigo.com"` (not tried here). `issuewild ";"` forbids wildcard
  certificates; drop it if you use one.
- **TXT** carries SPF, DMARC and the verification strings services ask for. One string holds at
  most 255 characters (BIND refuses longer ones with a syntax error); a long value, such as a
  2048-bit DKIM key, is written as several quoted strings in one record.

## Move a name without an outage

The time-to-live (TTL) on a record is how long resolvers may keep their copy. Lowering it on the
day of the move does nothing for the copies they already hold, so plan backwards:

1. At least one old TTL before the move (a day ahead when the TTL is 86400), set the TTL of the
   records you will change to 300. Check on an authoritative server:
   `dig +noall +answer app.example.com @<nameserver>` shows `300`.
2. Get the new server fully working and test it by name without DNS:
   `curl -sI --resolve app.example.com:443:203.0.113.20 https://app.example.com/`.
3. Change the record, with the person's yes. Check every authoritative server (next section).
4. Leave the old server running until its access log has gone quiet, which takes longer than
   the TTL because some clients keep an address as long as they run. Copying data written
   there in between is part of the move, not an afterthought.
5. Raise the TTL back to 3600 once the move is settled.

Moving the whole domain to another DNS host is a bigger job. Copy every record first, MX and
TXT included, because whatever is missing at the new host stops working when the NS change
lands, and the NS records at the registry are often cached for one or two days.

## Check against the authoritative servers, not a cache

A resolver (your laptop's, your provider's, a public one) answers from its cache until the TTL
runs out, so asking it right after a change shows the old answer and proves nothing. Ask each
of the domain's own servers and compare the SOA serial, which the DNS host raises on each
change:

```
for ns in $(dig +short NS example.com); do
  serial=$(dig +short SOA example.com @"$ns" | cut -d' ' -f3)
  echo "$ns: $(dig +short A app.example.com @"$ns") serial $serial"
done
```

Every line should show the new address and the same serial. Then see what the public sees with
`dig @one.one.one.one app.example.com` and `dig @dns.google app.example.com`: an old answer
there with a TTL still counting down is normal caching, not a fault. With a local BIND
authoritative server and a caching resolver in front of it, the authoritative server answered
with the new address while the resolver kept the old one until its TTL ran out. `dig +trace
app.example.com` follows the delegation from the root, which shows what the registry says
after a change of nameservers.

**Negative caching.** Asking for a name before it exists caches "no such name" (NXDOMAIN) for
as long as the zone's SOA record says (its last field, capped by the SOA's own TTL), often an
hour at DNS hosts. The local test showed it: a name added to the zone stayed NXDOMAIN at the
resolver while the authoritative server already answered. So create the record first and look
it up after, and do not let a CA try to validate a name before it exists, because the CA's
resolver caches the miss too. A lookup of a missing name shows how long:
`dig +noall +authority nothing-here.example.com @<nameserver>` prints the SOA record, and its
TTL there is the time a miss is cached.

## The AAAA record that points where nothing listens

The usual causes: an AAAA left over from the DNS host's default template or from the old
server, or a proxy that listens only on IPv4. It hides well. A browser on a network with IPv6
tries it, fails quickly and silently uses IPv4, so the site works for you. Meanwhile the
certificate authority prefers IPv6 and fails validation (it falls back to IPv4 only after a
timeout), some API clients and monitors fail outright, and visitors on networks that reach the
internet only over IPv6 cannot connect. When the AAAA points at an old server that still
answers, IPv6 visitors get the old site and nothing falls back at all.

Check from a machine with IPv6: `curl -6 -sI https://app.example.com/`. On the server,
`ss -tln '( sport = :443 )'` should show `[::]:443` or `*:443`. Fix it by making the proxy
listen on IPv6 (Caddy does by default; nginx needs the `listen [::]:443` lines) or by deleting
the AAAA record.

## Reverse DNS

A PTR record maps an address back to a name. It is set by whoever owns the address, which for a
server means the hosting provider's panel or API, not the domain's DNS host. A web app does not
need it. Mail does: receivers check that the sending address has a PTR and that the name it
gives resolves back to the same address. Check both directions:
`dig +short -x 203.0.113.10`, then `dig +short A <the name it printed>`.

## Sending mail from an app

Send through a transactional mail service over its API or SMTP submission (port 587 with
STARTTLS, or 465), not from a mail server on the app's own machine. The reasons are concrete:

- Many providers block outbound port 25 on new servers to stop spam, so direct delivery cannot
  even connect. Test with `nc -vz -w 5 <a receiving mail server> 25`: a timeout means blocked,
  while 587 to the mail service connects.
- A fresh address has no sending reputation and may carry a previous tenant's place on a
  blocklist, so even mail that leaves lands in spam.
- The service handles bounces, retries, complaint feedback and logs, which an app's own Postfix
  would leave to you.

The API key or SMTP password is a secret: keep it in the app's environment file or secret
store, never in the repository ([secrets.md](secrets.md)).

Large mailbox providers enforce authentication. Gmail requires SPF or DKIM and valid forward and
reverse DNS from every sender, and from senders of more than 5,000 messages a day SPF, DKIM and
DMARC with alignment and one-click unsubscribe for marketing mail; Outlook.com has required
SPF, DKIM and DMARC from high-volume senders since May 2025. Set up all three from the start.

**SPF** says which servers may send for a domain, as one TXT record:
`v=spf1 include:<the service's SPF domain> -all`. Exactly one `v=spf1` record per name: two of
them make SPF fail for every message, so add a second service as another `include:` in the
same record. The whole record may cause at most 10 DNS lookups, nested includes counted, before
it fails. SPF checks the envelope sender (the bounce address), which many services set to their
own domain unless you configure a custom bounce domain, so on its own SPF often does not align
with your From address.

**DKIM** signs each message; the service gives you a selector and either a CNAME (better: the
service can rotate keys) or a TXT record with the public key at
`<selector>._domainkey.example.com`. Check with `dig +short TXT s1._domainkey.example.com`,
which follows the CNAME, then confirm the service's dashboard shows the domain as verified.

**DMARC** tells receivers what to do when a message fails, and passes when SPF or DKIM passes
for a domain that matches the From address. Start with `p=none` and an `rua` address for the
daily reports. Read them for two to four weeks to find every service that sends as the domain
(newsletter tool, invoicing, help desk, office mail), then move to `p=quarantine` and later
`p=reject`. Each step changes what happens to the person's real mail, so each needs their yes;
starting at `p=reject` silently drops mail from the sender nobody remembered.

**Prove it** with one real message, with the person's yes, to a mailbox they own. In the
message's original headers, `Authentication-Results` should show `spf=pass`, `dkim=pass` with
`header.d=example.com` (the person's domain, not the service's) and `dmarc=pass`. Ask the person
to check the spam folder too.

## Traps

- **Records added at the registrar** while the NS records point elsewhere. Nothing happens.
- **A relative name in a zone file.** Without the trailing dot, `app.example.com` in a BIND zone
  becomes `app.example.com.example.com.`; in web panels the name is usually relative already.
- **A CNAME on a name that also needs MX or TXT,** the apex included. Refused or broken.
- **A CDN's proxy mode** on a record returns the CDN's addresses, so `dig` no longer shows the
  server, and the app sees the CDN's addresses as clients ([web-and-https.md](web-and-https.md)
  covers the real client address).
- **Losing MX and TXT records** when moving to a new DNS host. Mail stops and SPF fails.
- **Two SPF records,** often one from an old setup. SPF fails for all mail.

## Done means

- Every authoritative server returns the intended A, AAAA and CNAME answers with the same SOA
  serial, and the server answers on each address published (IPv6 tested from outside).
- TTLs are back to their normal values after a move, and the old records are saved.
- A CAA record, if there is one, names the CA the proxy uses.
- The app sends through a mail service, and one real message showed `spf=pass`, `dkim=pass`
  aligned with the From domain and `dmarc=pass`; DMARC is at `p=none` with reports going to an
  address someone reads, and the next step is in the hand-over.

Checked against: BIND 9.18.49 and dig 9.18.49 (Debian 12 packages: `named-checkzone`, a local
authoritative server and a caching resolver in front of it), only documentation names and
addresses, 2026-11-11.
