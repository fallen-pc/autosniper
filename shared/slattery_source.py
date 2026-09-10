"""Read public Slattery hydration without mixing unrelated lots or auction cycles.

Full URLs remain listing identities. Numeric aliases are accepted only from a
matched asset and its auction context, including the site's own detail route.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html import unescape
from html.parser import HTMLParser
import json
import re
from typing import Iterable
from urllib.parse import parse_qsl, unquote_plus, urlsplit, urlunsplit

from shared.auction_fees import extract_slattery_fee_fields


_SLATTERY_HOSTS = {"slatteryauctions.com.au", "www.slatteryauctions.com.au"}
_GRAYS_HOSTS = {"grays.com", "www.grays.com"}
_MARKETING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "gclid", "fbclid"}
_ID = r"(?:[1-9][0-9]*|[A-Za-z0-9]{15}|[A-Za-z0-9]{18})"
_ASSET_PATH = re.compile(rf"/assets/({_ID})/?$")
_STATES = {"NEW SOUTH WALES": "NSW", "VICTORIA": "VIC", "QUEENSLAND": "QLD", "WESTERN AUSTRALIA": "WA", "SOUTH AUSTRALIA": "SA", "TASMANIA": "TAS", "AUSTRALIAN CAPITAL TERRITORY": "ACT", "NORTHERN TERRITORY": "NT"}


def normalize_slattery_url(url: str) -> str:
    """Unwrap only the observed Grays referral route and remove known tracking."""
    value = unescape(str(url or "").strip())
    if value.startswith("/redirection/interimPage?"):
        value = "https://www.grays.com" + value
    try:
        parsed = urlsplit(value)
        if parsed.hostname in _GRAYS_HOSTS and parsed.path == "/redirection/interimPage":
            targets = [v for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k == "url"]
            if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port or len(targets) != 1:
                return ""
            parsed = urlsplit(targets[0])
        if parsed.scheme != "https" or parsed.hostname not in _SLATTERY_HOSTS or parsed.username or parsed.password or parsed.port:
            return ""
        if not _ASSET_PATH.fullmatch(parsed.path):
            return ""
        auctions = [v for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k == "auctionId"]
        if len(auctions) != 1 or not re.fullmatch(_ID, auctions[0]):
            return ""
        # Preserve unknown query values and their encoding; they may carry identity.
        query = "&".join(part for part in parsed.query.split("&") if unquote_plus(part.split("=", 1)[0]).lower() not in _MARKETING_PARAMS)
        return urlunsplit(("https", "slatteryauctions.com.au", parsed.path.rstrip("/"), query, parsed.fragment))
    except (ValueError, TypeError):
        return ""


def slattery_listing_identity(url: str) -> tuple[str, str] | None:
    clean = normalize_slattery_url(url)
    if not clean:
        return None
    parsed = urlsplit(clean)
    return parsed.path.rsplit("/", 1)[-1], dict(parse_qsl(parsed.query))["auctionId"]


class _Scripts(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.scripts: list[str] = []
        self._current: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            self._current = []

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._current.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._current is not None:
            self.scripts.append("".join(self._current))
            self._current = None


def _hydration_roots(html: str) -> list[object]:
    """Decode JSON, __NEXT_DATA__, and streamed Next flight JSON records.

    Flight transport strings may split in the middle of a JSON object. Joining
    decoded transport chunks reconstructs that stream; JSON objects themselves
    are decoded structurally rather than sliced at nearby price text.
    """
    roots: list[object] = []
    decoder = json.JSONDecoder()
    try:
        roots.append(json.loads(html))
    except (ValueError, TypeError):
        pass
    parser = _Scripts()
    parser.feed(html)
    chunks: list[str] = []
    for script in parser.scripts:
        try:
            roots.append(json.loads(script))
        except ValueError:
            pass
        for marker in re.finditer(r"self\.__next_f\.push\(", script):
            try:
                value, _ = decoder.raw_decode(script[marker.end():])
            except ValueError:
                continue
            if isinstance(value, list) and len(value) > 1 and value[0] == 1 and isinstance(value[1], str):
                chunks.append(value[1])
    stream = "".join(chunks).encode("utf-8")
    cursor = 0
    while cursor < len(stream):
        header = re.match(rb"[0-9a-fA-F]*:", stream[cursor:])
        if not header:
            break
        cursor += header.end()
        # Flight text records are byte-length framed, have no trailing newline,
        # and may contain strings that look like JSON or a following row header.
        text_header = re.match(rb"T([0-9a-fA-F]+),", stream[cursor:])
        if text_header:
            cursor += text_header.end() + int(text_header[1], 16)
            continue
        endline = stream.find(b"\n", cursor)
        if endline < 0:
            endline = len(stream)
        line = stream[cursor:endline].decode("utf-8", errors="replace")
        cursor = endline + 1
        try:
            value, end = decoder.raw_decode(line)
        except ValueError:
            continue
        if not line[end:].strip():
            roots.append(value)
    return roots


def _walk(value: object) -> Iterable[dict]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _text(value: object) -> str:
    if value is None or isinstance(value, (dict, list)):
        return ""
    text = " ".join(unescape(str(value)).split())
    return "" if text in {"$undefined", "null", "None"} else text


def _asset_ids(record: dict) -> set[str]:
    return {_text(record.get(key)) for key in ("id", "sfid")} - {""}


def _auction_ids(record: dict) -> set[str]:
    ids = {_text(record.get("auctionId")), *record.get("_auction_aliases", [])}
    auction = record.get("auction")
    if isinstance(auction, dict) and _text(auction.get("id")) == _text(record.get("auctionId")):
        ids.update(_text(auction.get(key)) for key in ("id", "sfid"))
    return ids - {""}


def extract_slattery_records(html: str) -> list[dict]:
    """Return public asset objects; private helper metadata is not a new key schema."""
    roots = _hydration_roots(html)
    nodes = [node for root in roots for node in _walk(root)]
    routes: set[tuple[str, str]] = set()
    for node in nodes:
        route = node.get("c")
        if isinstance(route, list) and len(route) == 3 and route[:2] == ["", "assets"] and isinstance(route[2], str):
            identity = slattery_listing_identity("https://slatteryauctions.com.au/assets/" + route[2])
            if identity:
                routes.add(identity)
    main_assets = {id(node["asset"]) for node in nodes if isinstance(node.get("asset"), dict)}
    records: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for node in nodes:
        if not (node.get("id") and node.get("auctionId") and node.get("name")):
            continue
        record = dict(node)
        record["_is_main_asset"] = id(node) in main_assets
        record["_auction_aliases"] = sorted(_auction_ids(record))
        if id(node) in main_assets and len(routes) == 1:
            route_asset, route_auction = next(iter(routes))
            # The explicit main route must address this asset's id or sfid.
            # A numeric auction mismatch proves a different auction cycle.
            if route_asset in _asset_ids(record) and (not route_auction.isdecimal() or route_auction == _text(record.get("auctionId"))):
                record["_auction_aliases"] = sorted({*record["_auction_aliases"], route_auction})
                record["_route_identity"] = [route_asset, route_auction]
        key = (_text(record.get("id")), _text(record.get("auctionId")), json.dumps(record, sort_keys=True))
        if key not in seen:
            records.append(record)
            seen.add(key)
    return records


def match_slattery_record(url: str, records: Iterable[dict]) -> dict | None:
    identity = slattery_listing_identity(url)
    if not identity:
        return None
    asset_id, auction_id = identity
    matched = [record for record in records if asset_id in _asset_ids(record) and auction_id in _auction_ids(record)]
    # Conflicting copies cannot silently turn into whichever record appeared last.
    return matched[0] if len(matched) == 1 else None


def canonical_slattery_url(url: str, records: Iterable[dict]) -> str:
    clean = normalize_slattery_url(url)
    record = match_slattery_record(clean, records)
    if not record:
        return clean
    asset, auction = _text(record.get("id")), _text(record.get("auctionId"))
    if not asset.isdecimal() or not auction.isdecimal():
        return clean
    parsed = urlsplit(clean)
    query = "&".join("auctionId=" + auction if unquote_plus(part.split("=", 1)[0]) == "auctionId" else part for part in parsed.query.split("&"))
    return urlunsplit((parsed.scheme, parsed.netloc, "/assets/" + asset, query, parsed.fragment))


def _number(value: object, *, integer: bool = False) -> str:
    raw = _text(value).replace(",", "")
    if not re.fullmatch(r"\d+(?:\.\d+)?", raw):
        return ""
    try:
        number = Decimal(raw)
    except InvalidOperation:
        return ""
    if integer and number != int(number):
        return ""
    return format(number, "f").rstrip("0").rstrip(".") if "." in format(number, "f") else str(number)


def _date(value: object) -> datetime | None:
    try:
        date = datetime.fromisoformat(_text(value).replace("Z", "+00:00"))
        return date.astimezone(timezone.utc) if date.tzinfo else None
    except ValueError:
        return None


def _state(value: str) -> str:
    upper = value.upper()
    for name, abbreviation in _STATES.items():
        if name in upper:
            return abbreviation
    match = re.search(r"\b(NSW|VIC|QLD|WA|SA|TAS|ACT|NT)\b", upper)
    return match[1] if match else ""


def _yes_no(value: object) -> str:
    text = _text(value)
    return {"true": "Yes", "false": "No"}.get(text.lower(), text)


def extract_slattery_listing(html: str, url: str, *, now: datetime | None = None) -> dict[str, str]:
    """Extract only the requested asset and auction; an unmatched page returns {}."""
    records = extract_slattery_records(html)
    main_records = [record for record in records if record.get("_is_main_asset")]
    if main_records:
        records = main_records
    asset = match_slattery_record(url, records)
    if asset is None:
        return {}
    detail = asset.get("detailAttributes") or {}
    summary = asset.get("summaryAttributes") or {}
    condition = asset.get("conditionAttributes") or {}
    if not all(isinstance(value, dict) for value in (detail, summary, condition)):
        return {}
    attrs = {**summary, **detail}
    row = {"source": "slattery", "url": canonical_slattery_url(url, records), "title": _text(asset.get("name")), "date_sold": "", "final_sale_price": "", "status": ""}
    row["year"] = _number(asset.get("manufactureYear") or attrs.get("yearofmanufacture"), integer=True)
    row["make"] = _text(attrs.get("make") or asset.get("make"))
    row["model"] = _text(attrs.get("model") or asset.get("model"))
    prefix = r"^" + r"\s+".join(re.escape(row[key]) for key in ("year", "make", "model") if row[key]) + r"\b\s*"
    variant = re.sub(prefix, "", row["title"], flags=re.I).strip()
    drive = _text(attrs.get("drivetype"))
    drive = {"front wheel drive": "FWD", "rear wheel drive": "RWD", "all wheel drive": "AWD", "four wheel drive": "4WD"}.get(drive.lower(), drive)
    for token in (_text(attrs.get("series")), drive):
        if token and not re.search(r"\b" + re.escape(token) + r"\b", variant, flags=re.I):
            variant = f"{variant} {token}".strip()
    row["variant"] = variant
    for field, key in {"body_type": "bodytype", "vin": "vin", "rego_no": "registrationnumber", "rego_expiry": "registrationexpiry", "engine_capacity": "capacity", "exterior_colour": "colour", "interior_colour": "interiorcolour"}.items():
        row[field] = _text(attrs.get(key))
    transmission = _text(attrs.get("transmission"))
    row["transmission"] = "CVT" if "cvt" in transmission.lower() else "Automatic" if "auto" in transmission.lower() else "Manual" if "manual" in transmission.lower() else transmission
    fuel = _text(attrs.get("fueltype"))
    row["fuel_type"] = "Hybrid" if "hybrid" in fuel.lower() else "Diesel" if "diesel" in fuel.lower() else "Petrol" if "petrol" in fuel.lower() else fuel
    row["odometer_reading"] = _number(attrs.get("odometer") if attrs.get("odometer") is not None else asset.get("odometer"), integer=True)
    row["no_of_seats"] = _number(attrs.get("noofseats"), integer=True)
    row["no_of_cylinders"] = _number(attrs.get("noofcylinders") or attrs.get("cylinders"), integer=True)
    for field, key in {"key": "keys", "spare_key": "sparekey", "owners_manual": "ownersmanual", "service_history": "logbook", "engine_turns_over": "engineturnsover"}.items():
        row[field] = _yes_no(attrs.get(key))
    site = asset.get("siteMaster") or {}
    site = site if isinstance(site, dict) else {}
    location = _text(asset.get("pickupLocation") or asset.get("inspectionLocation") or site.get("name"))
    state = _state(location) or _state(_text(site.get("siteAddress"))) or _state(_text(asset.get("deliveryNotes"))) or _state(_text(asset.get("inspectionNotes")))
    row["location"] = f"{location}, {state}" if location and state and not _state(location) else location
    row["rego_state"] = _state(_text(attrs.get("registrationstate")))
    description = _text(asset.get("description"))
    description_lines = [_text(line) for line in str(asset.get("description") or "").splitlines() if _text(line)]
    registration_notes: list[str] = []
    if _yes_no(attrs.get("soldunregistered")) == "Yes":
        row["rego_expiry"] = "Unregistered"
        registration_notes.append("Sold unregistered")
    elif re.search(r"sold unregistered to interstate buyers", description, flags=re.I):
        # A WA registration expiry is not transferable registration for a VIC buyer.
        row["rego_expiry"] = "Unregistered for interstate buyers"
        registration_notes.extend(line for line in description_lines if re.search(r"registered|registration|licence holders|rego", line, flags=re.I))
    elif re.search(r"\b(?:sold|selling)\b[^.!?]*\bunregistered\b", description, flags=re.I):
        row["rego_expiry"] = "Unregistered"
        registration_notes.extend(line for line in description_lines if re.search(r"unregistered", line, flags=re.I))
    elif re.search(r"\b(NO PLATES|UNREG(?:ISTERED)?)\b", row["rego_no"], flags=re.I):
        row["rego_expiry"] = "Unregistered"
    notes = []
    for key, value in condition.items():
        if not _text(value):
            continue
        label = re.sub(r"(condition|notes)$", r" \1", key).strip().capitalize()
        lines = [_text(line) for line in str(value).splitlines() if _text(line)]
        notes.append(f"{label}: " + " | ".join(lines))
    if _yes_no(attrs.get("regoplatestolicenseddealersonly")) == "Yes" or _yes_no(attrs.get("regoplatestolicnswdealersonly")) == "Yes":
        # The owner buys privately. Preserve the unregistered marker consumed
        # by roadworthy/transfer costing even when an expiry and plates exist.
        row["rego_expiry"] = "Unregistered for private buyers; registration restricted to licensed dealers"
        restricted_dealers = "licensed NSW dealers" if _yes_no(attrs.get("regoplatestolicnswdealersonly")) == "Yes" else "licensed dealers"
        registration_notes.append(f"Registration plates restricted to {restricted_dealers}")
    row["general_condition"] = " | ".join(notes + registration_notes)
    row["bids"] = _number(asset.get("bidCount"), integer=True)
    bid_values = []
    bid_times = []
    for bid in asset.get("auctionAssetBids") or []:
        if not isinstance(bid, dict):
            continue
        if _text(bid.get("assetId")) not in _asset_ids(asset) or _text(bid.get("auctionId")) not in _auction_ids(asset):
            continue
        amount = _number(bid.get("bidAmount"))
        if amount and Decimal(amount) > 0:
            bid_values.append(Decimal(amount))
        bid_time = _date(bid.get("bidAt"))
        if bid_time:
            bid_times.append(bid_time)
    current = _number(asset.get("currentBidAmount"))
    row["price"] = current if current and Decimal(current) > 0 else _number(max(bid_values)) if bid_values else ""
    if not row["price"] and row["bids"] == "0":
        row["price"] = _number(asset.get("startingBidAmount"))
    row["time_remaining_or_date_sold"] = _text(asset.get("closesAt"))
    closes = _date(asset.get("closesAt"))
    opens = _date(asset.get("opensAt"))
    current_time = now or datetime.now(timezone.utc)
    # These status IDs and two-minute bonus behavior are used by the public
    # online-auction timer (verified 2026-09-11); they are not sold-status enums.
    online_auction = asset.get("saleTypeId") == 1
    can_bid = asset.get("assetStatusId") in (7, 12)
    if closes and online_auction:
        last_close = _date(asset.get("lastAssetClosesAt"))
        last_bid = _date(asset.get("lastBidAt"))
        if last_bid:
            bid_times.append(last_bid)
        extensions = [closes]
        if last_close and last_close > current_time:
            extensions.append(last_close)
        if bid_times:
            extensions.append(max(bid_times) + timedelta(seconds=120))
        effective_close = max(extensions)
        if effective_close != closes:
            row["time_remaining_or_date_sold"] = effective_close.isoformat().replace("+00:00", "Z")
        closes = effective_close
    explicit = _text(asset.get("status") or asset.get("assetStatus")).lower()
    if explicit in {"withdrawn", "cancelled", "canceled"}:
        row["status"] = "Withdrawn"
    elif online_auction and closes and closes <= current_time:
        row["status"] = "Closed"
    elif online_auction and can_bid and opens and closes and opens < closes:
        row["status"] = "Upcoming" if opens > current_time else "Active"
    required = ["year", "make", "model", "odometer_reading", "vin", "location", "general_condition", "status"]
    if row["status"] == "Active":
        required.append("price")
    missing = [field for field in required if not row.get(field)]
    if not notes and "general_condition" not in missing:
        missing.append("general_condition")
    if not state:
        missing.append("location_state")
    row["detail_fields_missing"] = ",".join(missing)
    row["detail_completeness_status"] = "incomplete" if missing else "complete"
    row.update(extract_slattery_fee_fields(asset, row["url"]))
    return row
