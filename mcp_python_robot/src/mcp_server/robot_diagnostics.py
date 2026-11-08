"""Advisory diagnostics, not physical motor limits or clock inference."""
import math
import statistics
from datetime import datetime, timezone


# Only declared absolute clocks are comparable to a civil ISO timestamp. Never
# guess an epoch from timestamp magnitude (relative/device clocks can be large).
UTC_TIME_BASES = {"t_ns_utc_host_offset_corrected", "utc", "unix", "unix_epoch", "unix_ns"}


def metadata_start_time_warnings(spec, rows, meta):
    """Compare metadata to first telemetry sample, allowing 1 s rounding/lead-in.

    Missing timezone is ambiguous, not implicitly local or UTC. Unknown/relative
    clocks require an explicit mapping before this comparison can be performed.
    """
    value = meta.get("start_time")
    if value is None:
        return ["meta.start_time: missing; cannot compare with telemetry"]
    try:
        if not isinstance(value, str):
            raise ValueError("string required")
        start = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if start.tzinfo is None or start.utcoffset() is None:
            raise ValueError("timezone required")
        delta = start.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
        start_ns = (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000
    except (ValueError, TypeError, OverflowError):
        return ["meta.start_time: timezone-aware ISO datetime required"]
    time = spec.get("time", {})
    if time.get("unit") != "ns" or time.get("time_base") not in UTC_TIME_BASES:
        return ["meta.start_time: comparison skipped; telemetry clock is not a declared UTC/Unix clock"]
    first = rows[0].get(time.get("field")) if rows and isinstance(rows[0], dict) else None
    if type(first) is not int or not -(2**63) <= first < 2**63:
        return ["meta.start_time: comparison skipped; first telemetry timestamp unavailable or invalid"]
    offset_ns = start_ns - first
    if abs(offset_ns) > 1_000_000_000:
        return [f"meta.start_time: differs from first telemetry timestamp by {offset_ns / 1e9:.6f} s (tolerance 1 s)"]
    return []


def current_warnings(spec, rows):
    """Flag unbounded current and isolated statistical spikes per component.

    This is review evidence, not a safety rating. A spike must differ from the
    channel median by >10 MAD (with a relative 10% scale floor for flat signals)
    while both neighbors remain within that band. At least 5 samples are needed.
    """
    field = next((f for f in spec.get("fields", []) if f.get("name") == "current"), None)
    if not field:
        return []
    warnings = []
    if field.get("range") in (None, "?"):
        warnings.append("current: no configured range; physical current limits have not been validated")
    shape = field.get("shape", [])
    if len(shape) > 1 or field.get("dtype") not in ("float", "int", "int64"):
        return warnings
    size = shape[0] if shape else 1
    for component in range(size):
        values = []
        for row in rows:
            value = row.get("current") if isinstance(row, dict) else None
            if shape:
                value = value[component] if isinstance(value, list) and len(value) == size else None
            values.append(value if type(value) in (int, float) and math.isfinite(value) else None)
        valid = [v for v in values if v is not None]
        if len(valid) < 5:
            continue
        median = statistics.median(valid)
        mad = statistics.median(abs(v - median) for v in valid)
        band = 10 * max(mad, abs(median) * 0.1, 1e-12)
        spikes = [i for i in range(1, len(values) - 1)
                  if all(values[j] is not None for j in (i - 1, i, i + 1))
                  and abs(values[i] - median) > band
                  and all(abs(values[j] - median) <= band for j in (i - 1, i + 1))]
        if spikes:
            names = field.get("names", [])
            name = names[component] if component < len(names) else str(component)
            warnings.append(f"current {name}: isolated statistical outlier at rows {spikes[:20]}"
                            f" ({len(spikes)} total; baseline {median:g} {field.get('unit', '')}); review, not a physical limit")
    return warnings
