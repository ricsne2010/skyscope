"""Settings web page — the Pi's stand-in for the ESP32's setup portal.

Serves the settings at http://<pi>:<web_port>/radar_config (port 7700 by
default); the bare address redirects to the browser radar at /radar. A save is
handed to the render loop through a queue and applied there, so settings never
change mid-frame; the request waits until it has been applied before
redirecting.
"""

import html
import json
import queue
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from airports import AirportIndex
from filters import (ALT_BANDS, BUILTIN_PRESETS, CLASS_COLORS, CLASSES, PRESET_FIELDS,
                     AircraftFilter, all_presets, matching_preset, preset_changes)
from overlays import Overlays
from photos import PhotoLookup
from settings import MAX_RANGE_PRESETS, Settings
from version import VERSION

AIRPORT_INDEX = AirportIndex()
OVERLAYS = Overlays()  # SID/STAR counts for the Map tab (loaded on first use)
PHOTOS = PhotoLookup()  # aircraft photos for the browser card

COUNTRY_NAMES = AircraftFilter().countries
FILTER_MODES = [("off", "Off"), ("only", "Show only"), ("hide", "Hide")]

RADAR_PAGE = Path(__file__).resolve().parent / "web" / "radar.html"
DOCS_DIR = Path(__file__).resolve().parent / "docs"
# The guide and its images/PDF: only these file types, only inside docs/.
DOCS_PATH_RE = re.compile(r"^/docs/((?:images/)?[A-Za-z0-9._-]+\.(html|jpg|png|pdf))$")
DOCS_TYPES = {"html": "text/html; charset=utf-8", "jpg": "image/jpeg", "png": "image/png", "pdf": "application/pdf"}
CONFIG_PATH = "/radar_config"
GPS_NOW_PATH = "/radar_config/gps-now"
LOGO_PATH_RE = re.compile(r"^/logo/([A-Z]{3})\.png$")
# Save-bar messages after a redirect (?saved=1 etc.).
NOTICES = {"presetsaved": "Preset saved", "applied": "Preset applied", "deleted": "Preset deleted",
           "saved": "Saved", "gps": "Saved; reading position from GPS"}
PRESET_NAME_RE = re.compile(r"^[\w ,.&()'+/-]{1,40}$")
ICAO_RE = re.compile(r"^[A-Z0-9]{3,4}$")

# name → (label, kind, extra). Kinds: bool, float (min, max), text (max length),
# choice [(value, label)], multi [(value, label)], classes, bands,
# codes (pattern, max length), countries, watch (max length), airport,
# procedures.
FIELDS = [
    ("location_source", "Location source", "choice",
     [("manual", "Manual"), ("gps_once", "GPS once"), ("gps_live", "GPS live")]),
    ("lat", "Latitude", "float", (-90.0, 90.0)),
    ("lon", "Longitude", "float", (-180.0, 180.0)),
    ("gps_update_s", "Update every", "float", (5.0, 3600.0)),
    ("center_airport", "Centre on an airport", "airport", None),
    ("data_source", "Aircraft data from", "choice",
     [("internet", "Internet (adsb.fi)"), ("sdr", "SDR receiver")]),
    ("sdr_location", "Receiver data location", "text", 300),
    ("distance_unit", "Distance", "choice", [("km", "km"), ("mi", "mi"), ("nm", "nm")]),
    ("speed_unit", "Speed", "choice", [("kt", "kt"), ("kmh", "km/h"), ("mph", "mph")]),
    ("altitude_unit", "Altitude", "choice", [("ft", "ft"), ("m", "m")]),
    ("show_airspeed", "Show true airspeed (TAS) beside ground speed", "bool", None),
    ("range_index", "Range", "choice", [(str(i), str(i)) for i in range(MAX_RANGE_PRESETS)]),
    ("aircraft_symbol", "Aircraft symbols", "choice",
     [("silhouette", "Silhouettes"), ("triangle", "Triangles")]),
    ("color_by_kind", "Colour aircraft by kind", "bool", None),
    ("airline_logos", "Airline logos", "choice",
     [("off", "Off"), ("panel", "Panel"), ("all", "Panel + radar")]),
    ("show_photos", "Aircraft photo on the card", "bool", None),
    ("show_routes", "Flight route on the card (airline flights)", "bool", None),
    ("show_beyond_dots", "Dots for aircraft just outside the range", "bool", None),
    ("show_ground", "Aircraft on the ground", "bool", None),
    ("sweep_enabled", "Radar sweep", "bool", None),
    ("sweep_period_s", "Seconds per turn", "float", (1.0, 30.0)),
    ("sweep_trail_deg", "Trail length (°)", "float", (10.0, 360.0)),
    ("show_runways", "Show airports and runways", "bool", None),
    ("runway_types", "Airports shown", "multi",
     [("L", "Major"), ("M", "Regional"), ("S", "Small (paved)")]),
    ("runway_centerlines", "Extended centrelines (10 nm, mile ticks)", "bool", None),
    ("show_airspace", "Class B, C and D airspace (US)", "bool", None),
    ("procedure_mode", "Show", "choice",
     [("both", "As ticked below"), ("sid", "SIDs only"), ("star", "STARs only"), ("off", "None")]),
    ("procedure_airports", "SIDs / STARs by airport", "procedures", None),
    ("highlight_emergencies", "Highlight emergency squawks (7500 / 7600 / 7700)", "bool", None),
    ("watchlist", "Watchlist", "watch", 1000),
    ("watch_notice", "Show a notice when a watched aircraft is in range", "bool", None),
    ("hidden_classes", "Kinds of aircraft", "classes", CLASSES),
    ("hidden_alt_bands", "Altitude", "bands", ALT_BANDS),
    ("type_mode", "Aircraft types", "choice", FILTER_MODES),
    ("type_filter", "Type codes", "codes", (r"[A-Z0-9*?]{1,6}", 400)),
    ("operator_mode", "Airlines / operators", "choice", FILTER_MODES),
    ("operator_filter", "Airline codes", "codes", (r"[A-Z*?]{1,3}", 400)),
    ("country_mode", "Country of registration", "choice", FILTER_MODES),
    ("country_filter", "Countries", "countries", None),
]
BY_NAME = {f[0]: f for f in FIELDS}

HINTS = {
    "lat": "Used when the source is Manual.",
    "watchlist": "Callsigns, registrations, ICAO addresses or type codes, separated by "
                 "commas or new lines. * matches anything: ENY*, N123AB, B52, A0B1C2.",
    "type_filter": "e.g. B738, A32*, C172. * matches anything (B73* = every 737).",
    "operator_filter": "The three letters starting the callsign, e.g. AAL, SWA, UAL.",
    "sdr_location": "\"auto\" finds readsb or dump1090, or give a path / URL to aircraft.json.",
}
# Hints that follow the chosen value of a segmented control.
CHOICE_HINTS = {
    "location_source": {
        "manual": "Type the position, or centre on an airport or this computer's location.",
        "gps_once": "Reads the GPS when the radar starts, then stays put: for a fixed installation.",
        "gps_live": "Keeps re-centring as the GPS moves: for a mobile radar.",
    },
    "data_source": {
        "internet": "Live data from adsb.fi. Needs a network connection.",
        "sdr": "A USB receiver on this computer, decoded by readsb or dump1090. No internet needed.",
    },
}
# Fields shown only while another field has a given value.
SHOW_WHEN = {"gps_update_s": "location_source=gps_live", "sdr_location": "data_source=sdr",
             "sweep_period_s": "sweep_enabled=on",
             "sweep_trail_deg": "sweep_enabled=on", "runway_types": "show_runways=on",
             "runway_centerlines": "show_runways=on",
             "type_filter": "type_mode=only|hide", "operator_filter": "operator_mode=only|hide",
             "country_filter": "country_mode=only|hide"}
UNITS = {"gps_update_s": "s"}
TABS = [("general", "General"), ("display", "Display"), ("map", "Map"), ("filters", "Filters"),
        ("presets", "Presets"), ("alerts", "Alerts"), ("about", "About")]
REPO = "https://github.com/ricsne2010"

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SkyScope settings</title>
<link rel="icon" href="/docs/images/moon-pi-logo-128.png">
<style>
  :root { --bg: #040a1c; --card: #0a1530; --field: #071028; --line: #1d2f55; --text: #e8ecf2;
          --dim: #8a9abb; --green: #46ff78; --amber: #ffc800; --red: #ff5a5a; --hover: #13284a; }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text);
         font: 15px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
  header { position: sticky; top: 0; z-index: 5; background: rgba(4, 10, 28, .94); backdrop-filter: blur(8px);
           border-bottom: 1px solid var(--line); }
  .bar { max-width: 1240px; margin: 0 auto; display: flex; align-items: center; gap: 14px; padding: 12px 24px 0; }
  header img.logo { width: 38px; height: 38px; }
  header h1 { margin: 0; font-size: 1.2rem; color: var(--green); letter-spacing: .05em; }
  header .crumb { color: var(--dim); font-weight: 600; }
  header a.guide { margin-left: auto; color: var(--dim); font-weight: 700; text-decoration: none; }
  header a.guide:hover { color: var(--text); }
  header a.radar { color: var(--bg); background: var(--green); font-weight: 700;
                   padding: 8px 14px; border-radius: 8px; text-decoration: none; }
  nav { max-width: 1240px; margin: 0 auto; display: flex; gap: 4px; padding: 10px 24px 0; overflow-x: auto; }
  nav button { background: none; color: var(--dim); font: inherit; font-weight: 700; border: 0;
               border-bottom: 3px solid transparent; padding: 8px 14px 10px; cursor: pointer; border-radius: 0; }
  nav button:hover { color: var(--text); }
  nav button.on { color: var(--green); border-bottom-color: var(--green); }
  main { max-width: 1240px; margin: 0 auto; padding: 22px 24px 110px; }
  .banner { padding: 10px 14px; border-radius: 10px; margin-bottom: 16px; }
  .banner.err { background: #64101088; border: 1px solid var(--red); }
  section.tab { display: none; }
  section.tab.on { display: block; }
  .tab-intro { color: var(--dim); margin: -4px 0 16px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 18px; align-items: start; }
  .about-head { display: flex; gap: 22px; align-items: center; margin-bottom: 18px; }
  .about-head img { width: 132px; height: 132px; flex: none; }
  .about-head h2 { margin: 0; font-size: 1.9rem; color: var(--green); letter-spacing: .05em; }
  .about-head .sub { color: var(--dim); font-weight: 600; }
  .about-head p { margin: 8px 0 0; max-width: 640px; }
  dl.facts { display: grid; grid-template-columns: max-content 1fr; gap: 6px 16px; margin: 0; }
  dl.facts dt { color: var(--dim); font-weight: 600; }
  dl.facts dd { margin: 0; overflow-wrap: anywhere; }
  ul.links { list-style: none; padding: 0; margin: 0; }
  ul.links li { padding: 7px 0; border-top: 1px solid var(--line); }
  ul.links li:first-child { border-top: 0; }
  .card p a { color: var(--green); font-weight: 700; }
  ul.links a { color: var(--green); font-weight: 700; text-decoration: none; }
  ul.links a:hover { text-decoration: underline; }
  ul.links span { display: block; color: var(--dim); font-size: .9rem; }
  .card { background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 16px 18px 18px; }
  .card.wide { grid-column: 1 / -1; }
  .card h2 { margin: 0 0 4px; font-size: .8rem; letter-spacing: .09em; text-transform: uppercase; color: var(--amber); }
  .field { margin-top: 14px; }
  .field > .label { font-weight: 600; margin-bottom: 6px; }
  .hint { color: var(--dim); font-size: .85rem; margin-top: 6px; }
  .row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  input[type=number], input[type=text], select, textarea {
    width: 100%; padding: 9px 11px; background: var(--field); color: var(--text);
    border: 1px solid var(--line); border-radius: 8px; font: inherit; }
  textarea { min-height: 84px; resize: vertical; text-transform: uppercase; }
  input:disabled { opacity: .45; }
  .with-unit { display: flex; align-items: center; gap: 8px; }
  .with-unit span { color: var(--dim); }
  /* Segmented control: radio buttons styled as a button row. */
  .seg { display: flex; flex-wrap: wrap; border: 1px solid var(--line); border-radius: 9px; overflow: hidden; }
  .seg label { flex: 1 1 auto; position: relative; }
  .seg input { position: absolute; opacity: 0; pointer-events: none; }
  .seg span { display: block; padding: 8px 10px; text-align: center; cursor: pointer; white-space: nowrap;
              background: var(--field); border-right: 1px solid var(--line); font-weight: 600; color: var(--dim); }
  .seg label:last-child span { border-right: 0; }
  .seg span:hover { color: var(--text); }
  .seg input:checked + span { background: var(--green); color: var(--bg); }
  .seg input:focus-visible + span { outline: 2px solid var(--amber); outline-offset: -2px; }
  /* Switches for on/off options: the whole row is the button. */
  label.toggle { display: flex; align-items: center; gap: 12px; margin-top: 10px; padding: 6px 4px;
                 border-radius: 8px; cursor: pointer; }
  label.toggle:hover { background: var(--hover); }
  label.toggle input { position: absolute; opacity: 0; }
  .switch { flex: none; width: 40px; height: 23px; border-radius: 12px; background: #2a3a60; position: relative; transition: .15s; }
  .switch::after { content: ""; position: absolute; top: 3px; left: 3px; width: 17px; height: 17px;
                   border-radius: 50%; background: #c8d0e0; transition: .15s; }
  label.toggle input:checked + .switch { background: var(--green); }
  label.toggle input:checked + .switch::after { left: 20px; background: var(--bg); }
  label.toggle input:focus-visible + .switch { outline: 2px solid var(--amber); }
  /* Tick rows: large click targets that light up when ticked. */
  .ticks { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 8px; }
  label.tick { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-radius: 9px;
               border: 1px solid var(--line); background: var(--field); cursor: pointer; user-select: none;
               font-weight: 600; transition: background .1s, border-color .1s; }
  label.tick:hover { background: var(--hover); }
  label.tick:has(input:checked) { border-color: #46ff7899; background: #10642040; }
  label.tick input { width: 18px; height: 18px; margin: 0; accent-color: var(--green); flex: none; cursor: pointer; }
  label.tick .sw { width: 12px; height: 12px; border-radius: 3px; flex: none; }
  label.tick.sm { padding: 6px 10px; font-weight: 600; }
  .swatch { width: 12px; height: 12px; border-radius: 3px; display: inline-block; }
  .legend { display: flex; flex-wrap: wrap; gap: 4px 14px; color: var(--dim); font-size: .85rem; margin-top: 8px; }
  .legend span { display: inline-flex; align-items: center; gap: 6px; }
  .status { margin-top: 12px; padding: 9px 12px; border-radius: 8px; background: var(--field); color: var(--dim); font-size: .9rem; }
  .buttons { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 12px; }
  button { font: inherit; font-weight: 700; border: 0; border-radius: 8px; padding: 9px 14px; cursor: pointer; }
  button.secondary { background: #2a3a60; color: var(--text); }
  button.secondary:hover { background: #34497a; }
  button.danger { background: transparent; color: var(--red); border: 1px solid #ff5a5a66; }
  button.link { background: none; color: var(--green); padding: 0 4px; font-weight: 600; }
  .countries { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 6px;
               max-height: 300px; overflow-y: auto; margin-top: 8px; padding: 2px; }
  .chip { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; padding: 7px 10px;
          border-radius: 8px; background: #10642055; border: 1px solid #46ff7866; }
  .chip b { color: var(--green); }
  .chip button.link { margin-left: auto; color: var(--dim); }
  .results { margin-top: 6px; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
  .results button { display: block; width: 100%; text-align: left; border-radius: 0; background: var(--field);
                    color: var(--text); font-weight: 400; padding: 8px 11px; border-bottom: 1px solid var(--line); }
  .results button:last-child { border-bottom: 0; }
  .results button:hover, .results button:focus { background: var(--hover); }
  .results b { color: var(--green); margin-right: 6px; }
  .results small { color: var(--dim); }
  table.procs { width: 100%; border-collapse: separate; border-spacing: 0 6px; margin-top: 6px; }
  table.procs th { color: var(--dim); font-size: .8rem; text-align: left; font-weight: 700; padding: 0 8px; }
  table.procs td { background: var(--field); padding: 6px 8px; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
  table.procs td:first-child { border-left: 1px solid var(--line); border-radius: 9px 0 0 9px; }
  table.procs td:last-child { border-right: 1px solid var(--line); border-radius: 0 9px 9px 0; }
  table.procs td.ap b { color: var(--green); }
  table.procs td.ap small, table.procs td.name small { color: var(--dim); }
  table.procs td.pick { width: 150px; white-space: nowrap; }
  table.procs label.tick { padding: 6px 10px; }
  .scroll { max-height: 460px; overflow-y: auto; }
  .preset-list { display: grid; gap: 6px; margin-top: 8px; }
  .preset-list div { display: flex; gap: 10px; padding: 8px 12px; border-radius: 8px; background: var(--field); }
  .preset-list div.on { border: 1px solid #46ff7899; }
  .preset-list b { min-width: 230px; }
  .preset-list span { color: var(--dim); }
  [hidden] { display: none !important; }
  /* Save bar: always in reach, shows when there are unsaved edits. */
  .savebar { position: fixed; left: 0; right: 0; bottom: 0; z-index: 5; display: flex; align-items: center;
             gap: 16px; padding: 12px 24px; background: rgba(10, 21, 48, .95); backdrop-filter: blur(8px);
             border-top: 1px solid var(--line); }
  .savebar .state { color: var(--dim); font-weight: 600; }
  .savebar.dirty .state { color: var(--amber); }
  .savebar.error .state { color: var(--red); }
  .savebar button.save { margin-left: auto; background: #2a3a60; color: var(--text); padding: 10px 26px; }
  .savebar.dirty button.save { background: var(--green); color: var(--bg); }
  @media (max-width: 600px) {
    .bar, nav, main, .savebar { padding-left: 14px; padding-right: 14px; }
    .grid { grid-template-columns: 1fr; }
    table.procs td.name { display: none; }
  }
</style></head><body>
<header><div class="bar"><img class="logo" src="/docs/images/moon-pi-logo-128.png" alt="Project Moon Pi"><h1>SKYSCOPE</h1><span class="crumb">Settings</span>
  <a class="guide" href="/guide" target="_blank">Guide</a>
  <a class="radar" href="/radar">Open radar &rarr;</a></div>
  <nav>%%TABS%%</nav></header>
<form method="post" action="/radar_config" id="form">
<main>
%%BANNER%%
%%BODY%%
</main>
<div class="savebar%%BARCLASS%%" id="savebar"><span class="state" id="state">%%STATE%%</span>
  <button type="submit" class="save" name="action" value="save">Save</button></div>
</form>
<script>
  const form = document.getElementById('form');
  const bar = document.getElementById('savebar'), state = document.getElementById('state');
  let dirty = false;
  function markDirty() {
    dirty = true; bar.className = 'savebar dirty'; state.textContent = 'Unsaved changes';
  }
  form.addEventListener('input', e => { if (!e.target.closest('[data-nodirty]')) markDirty(); });
  form.addEventListener('submit', () => { dirty = false; });
  window.addEventListener('beforeunload', e => { if (dirty) { e.preventDefault(); e.returnValue = ''; } });

  // Tabs: one section at a time; remembered across saves.
  const tabs = document.querySelectorAll('nav button[data-tab]');
  function showTab(id) {
    for (const b of tabs) b.classList.toggle('on', b.dataset.tab === id);
    for (const s of document.querySelectorAll('section.tab')) s.classList.toggle('on', s.id === 'tab-' + id);
    bar.hidden = id === 'about';  // nothing to save there
    try { sessionStorage.setItem('radarTab', id); } catch (e) {}
  }
  for (const b of tabs) b.addEventListener('click', () => showTab(b.dataset.tab));
  let startTab = 'general';
  try { startTab = sessionStorage.getItem('radarTab') || startTab; } catch (e) {}
  if (location.hash.length > 1) startTab = location.hash.slice(1);  // e.g. /radar_config#about
  showTab(document.getElementById('tab-' + startTab) ? startTab : 'general');

  // Current value of a field: radio group, checkbox ("on"/""), or input.
  function valueOf(name) {
    const els = form.querySelectorAll('[name="' + name + '"]');
    for (const el of els) {
      if (el.type === 'radio') { if (el.checked) return el.value; }
      else if (el.type === 'checkbox') return el.checked ? 'on' : '';
      else return el.value;
    }
    return '';
  }
  // Show fields only when relevant; swap hints that follow a choice.
  function syncVisibility() {
    for (const el of document.querySelectorAll('[data-when]')) {
      const [name, values] = el.dataset.when.split('=');
      el.hidden = !values.split('|').includes(valueOf(name));
    }
    for (const el of document.querySelectorAll('[data-hint-for]')) {
      el.hidden = valueOf(el.dataset.hintFor) !== el.dataset.hintValue;
    }
    const manual = valueOf('location_source') === 'manual';
    for (const n of ['lat', 'lon']) form.querySelector('[name=' + n + ']').disabled = !manual;
  }
  form.addEventListener('change', syncVisibility); syncVisibility();

  const escHtml = t => String(t).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  // Search box with a results list (airports for the centre and for SIDs/STARs).
  function airportSearch(input, results, onPick, extra = '') {
    let timer;
    input.addEventListener('input', () => {
      clearTimeout(timer);
      const q = input.value.trim();
      if (q.length < 2) { results.hidden = true; return; }
      timer = setTimeout(async () => {
        const found = await (await fetch('/api/airports?q=' + encodeURIComponent(q) + extra)).json();
        results.innerHTML = found.length ? found.map(a =>
          `<button type="button" data-ident="${escHtml(a.ident)}" data-name="${escHtml(a.name)}" data-lat="${a.lat}" data-lon="${a.lon}" data-sids="${a.sids ?? ''}" data-stars="${a.stars ?? ''}">` +
          `<b>${escHtml(a.ident)}${a.iata ? ' / ' + escHtml(a.iata) : ''}</b>${escHtml(a.name)} ` +
          `<small>${escHtml([a.city, a.country].filter(Boolean).join(', '))} · ${a.type}` +
          `${a.sids !== undefined ? ` · ${a.sids} SIDs, ${a.stars} STARs` : ''}</small></button>`).join('')
          : '<button type="button" disabled>No airports found</button>';
        results.hidden = false;
      }, 200);
    });
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); const first = results.querySelector('button[data-ident]'); if (first) first.click(); }
    });
    results.addEventListener('click', e => {
      const b = e.target.closest('button[data-ident]');
      if (!b) return;
      onPick(b.dataset); results.hidden = true; input.value = '';
    });
  }

  // Centre on an airport.
  const apField = form.querySelector('[name=center_airport]');
  const apCurrent = document.getElementById('airport-current'), apName = document.getElementById('airport-name');
  airportSearch(document.getElementById('airport-search'), document.getElementById('airport-results'), a => {
    apField.value = a.ident;
    form.querySelector('[name=lat]').value = a.lat;
    form.querySelector('[name=lon]').value = a.lon;
    apName.textContent = a.ident + ' · ' + a.name;
    apCurrent.hidden = false; markDirty();
  });
  document.getElementById('airport-clear').addEventListener('click', () => {
    apField.value = ''; apCurrent.hidden = true; markDirty();
  });
  // Typing coordinates by hand means the scope is no longer on an airport.
  for (const n of ['lat', 'lon']) form.querySelector('[name=' + n + ']').addEventListener('input', () => {
    apField.value = ''; apCurrent.hidden = true;
  });

  // SIDs/STARs: add an airport to the list, and tick/untick whole columns.
  const procList = form.querySelector('[name=proc_list]'), procBody = document.getElementById('proc-rows');
  airportSearch(document.getElementById('proc-search'), document.getElementById('proc-results'), a => {
    const ids = procList.value ? procList.value.split(',') : [];
    if (!a.sids && !a.stars) { alert(a.ident + ' has no published SIDs or STARs.'); return; }
    if (!ids.includes(a.ident)) {
      ids.unshift(a.ident); procList.value = ids.join(',');
      procBody.insertAdjacentHTML('afterbegin', `<tr><td class="ap"><b>${escHtml(a.ident)}</b></td>` +
        `<td class="name">${escHtml(a.name)}</td>` +
        `<td class="pick"><label class="tick sm"><input type="checkbox" name="proc_sid_${a.ident}" checked>${a.sids} SIDs</label></td>` +
        `<td class="pick"><label class="tick sm"><input type="checkbox" name="proc_star_${a.ident}" checked>${a.stars} STARs</label></td></tr>`);
      document.getElementById('proc-empty')?.remove();
    }
    markDirty();
  }, '&procedures=1');
  for (const b of document.querySelectorAll('[data-tick-all]')) b.addEventListener('click', () => {
    const [prefix, on] = b.dataset.tickAll.split(':');
    for (const el of form.querySelectorAll(`[name^="${prefix}"]`)) el.checked = on === '1';
    markDirty();
  });

  const search = document.getElementById('country-search');
  search.addEventListener('input', () => {
    const q = search.value.trim().toLowerCase();
    for (const el of document.querySelectorAll('label.country'))
      el.style.display = el.textContent.toLowerCase().includes(q) ? '' : 'none';
  });
  search.addEventListener('keydown', e => { if (e.key === 'Enter') e.preventDefault(); });

  // Browsers only share location with secure pages (https or localhost), so
  // this works on the computer running the radar, not from a phone viewing a Pi.
  // The OS supplies the position (on a laptop, usually from nearby Wi-Fi).
  const geo = document.getElementById('geo'), geoNote = document.getElementById('geo-note');
  if (window.isSecureContext && navigator.geolocation) {
    geo.hidden = false;
    geo.addEventListener('click', () => {
      geo.disabled = true; geo.textContent = 'Finding location...';
      navigator.geolocation.getCurrentPosition(pos => {
        form.querySelector('[name=location_source][value=manual]').checked = true; syncVisibility();
        form.querySelector('[name=lat]').value = pos.coords.latitude.toFixed(6);
        form.querySelector('[name=lon]').value = pos.coords.longitude.toFixed(6);
        apField.value = '';
        dirty = false; form.requestSubmit(form.querySelector('button.save'));
      }, err => {
        geo.disabled = false; geo.textContent = "Use this computer's location";
        geoNote.hidden = false;
        geoNote.textContent = 'Location not available: ' + err.message +
          '. Check that Location Services are on for this browser.';
      }, { enableHighAccuracy: true, timeout: 20000, maximumAge: 60000 });
    });
  }

  // "Clear filters" resets the filter controls on the page (save to apply).
  document.getElementById('clear-filters').addEventListener('click', () => {
    for (const el of form.querySelectorAll('[name^=class_], [name^=band_]')) el.checked = true;
    for (const n of ['type_mode', 'operator_mode', 'country_mode'])
      form.querySelector('[name=' + n + '][value=off]').checked = true;
    for (const el of form.querySelectorAll('[name=country]')) el.checked = false;
    syncVisibility(); markDirty();
  });
</script>
</body></html>
"""


def lan_address() -> str:
    """This machine's LAN IP (no packet is actually sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


# --- parsing ---------------------------------------------------------------------

def parse_form(form: dict[str, list[str]]) -> tuple[dict, list[str]]:
    """Validate a submitted form into {setting: value}; returns (changes, errors)."""
    changes, errors = {}, []
    source = (form.get("location_source") or ["manual"])[0]
    for name, label, kind, extra in FIELDS:
        if name in ("lat", "lon") and source != "manual":
            continue  # GPS owns the position; don't overwrite it with stale form values
        raw = (form.get(name) or [""])[0].strip()
        if kind == "bool":
            changes[name] = name in form  # unchecked boxes aren't submitted
        elif kind == "float":
            try:
                v = float(raw)
            except ValueError:
                errors.append(f"{label}: not a number")
                continue
            lo, hi = extra
            if not lo <= v <= hi:
                errors.append(f"{label}: must be between {lo:g} and {hi:g}")
                continue
            changes[name] = v
        elif kind == "text":
            if not raw or len(raw) > extra:
                errors.append(f"{label}: enter \"auto\" or a path/URL")
                continue
            changes[name] = raw
        elif kind == "multi":
            changes[name] = [v for v, _ in extra if f"{name}_{v}" in form]
        elif kind == "procedures":
            # One row per airport offered; ticked SID/STAR boxes make the choice.
            chosen = {}
            for ident in (form.get("proc_list") or [""])[0].upper().split(","):
                if not ICAO_RE.match(ident) or OVERLAYS.counts(ident) == (0, 0):
                    continue
                sid, star = f"proc_sid_{ident}" in form, f"proc_star_{ident}" in form
                if sid or star:
                    chosen[ident] = "both" if sid and star else "sid" if sid else "star"
            changes[name] = chosen
        elif kind == "classes":
            changes[name] = [cid for cid, _ in extra if f"class_{cid}" not in form]
        elif kind == "bands":
            changes[name] = [bid for bid, _ in extra if f"band_{bid}" not in form]
        elif kind in ("codes", "watch"):
            pattern, max_len = extra if kind == "codes" else (r"[A-Z0-9*?-]{1,10}", extra)
            codes = [c for c in re.split(r"[\s,;]+", raw.upper()) if c]
            bad = [c for c in codes if not re.fullmatch(pattern, c)]
            if bad or len(raw) > max_len:
                errors.append(f"{label}: not understood: {', '.join(bad[:5]) or 'too long'}")
                continue
            changes[name] = ", ".join(codes)
        elif kind == "airport":
            if not raw:
                changes[name] = ""
            elif (ap := AIRPORT_INDEX.get(raw)) is None:
                errors.append(f"{label}: unknown airport {raw}")
            else:
                changes[name] = ap["ident"]
                if source == "manual":  # the airport's position is the centre
                    changes["lat"], changes["lon"] = ap["lat"], ap["lon"]
        elif kind == "countries":
            changes[name] = [c for c in form.get("country", []) if c in COUNTRY_NAMES]
        elif kind == "choice":
            if raw not in [value for value, _ in extra]:
                errors.append(f"{label}: invalid choice")
                continue
            changes[name] = int(raw) if name == "range_index" else raw
    return changes, errors


def apply_preset_action(form: dict, changes: dict, st: Settings) -> list[str]:
    """Handle the preset buttons. Edits `changes`; returns errors."""
    action = (form.get("action") or ["save"])[0]
    chosen = (form.get("preset") or [""])[0]
    if action == "apply_preset":
        found = preset_changes(st, chosen)
        if not found:
            return ["Choose a preset to apply"]
        changes.update(found)
    elif action == "save_preset":
        name = (form.get("preset_name") or [""])[0].strip()
        if not PRESET_NAME_RE.match(name):
            return ["Preset name: 1-40 letters, numbers or spaces"]
        if name in BUILTIN_PRESETS:
            return [f"\"{name}\" is a built-in preset; choose another name"]
        values = {f: changes.get(f, getattr(st, f)) for f in PRESET_FIELDS}
        changes["filter_presets"] = {**st.filter_presets, name: values}
    elif action == "delete_preset":
        if chosen not in st.filter_presets:
            return ["Only your own presets can be deleted"]
        changes["filter_presets"] = {k: v for k, v in st.filter_presets.items() if k != chosen}
    return []


# --- rendering -------------------------------------------------------------------

def esc(text) -> str:
    return html.escape(str(text), quote=True)


def field(name: str, control: str, label: str | None = None, hint: str | None = None) -> str:
    when = SHOW_WHEN.get(name)
    attrs = f' data-when="{esc(when)}"' if when else ""
    label = BY_NAME[name][1] if label is None else label
    label_html = f'<div class="label">{esc(label)}</div>' if label else ""
    hint = HINTS.get(name) if hint is None else hint
    hint_html = f'<div class="hint">{esc(hint)}</div>' if hint else ""
    choice_hints = "".join(
        f'<div class="hint" data-hint-for="{name}" data-hint-value="{esc(v)}">{esc(h)}</div>'
        for v, h in CHOICE_HINTS.get(name, {}).items())
    return f'<div class="field"{attrs}>{label_html}{control}{hint_html}{choice_hints}</div>'


def seg(name: str, options, value) -> str:
    items = "".join(
        f'<label><input type="radio" name="{name}" value="{esc(v)}"'
        f'{" checked" if str(value) == v else ""}><span>{esc(t)}</span></label>'
        for v, t in options)
    return f'<div class="seg" role="radiogroup">{items}</div>'


def toggle(name: str, st: Settings) -> str:
    when = SHOW_WHEN.get(name)
    attrs = f' data-when="{esc(when)}"' if when else ""
    checked = " checked" if getattr(st, name) else ""
    return (f'<label class="toggle"{attrs}><input type="checkbox" name="{name}"{checked}>'
            f'<span class="switch"></span><span>{esc(BY_NAME[name][1])}</span></label>')


def number(name: str, st: Settings, label: str | None = None) -> str:
    lo, hi = BY_NAME[name][3]
    value = getattr(st, name)
    unit = UNITS.get(name)
    box = (f'<input type="number" step="any" min="{lo:g}" max="{hi:g}" name="{name}" '
           f'value="{value:g}">')
    if unit:
        box = f'<div class="with-unit">{box}<span>{esc(unit)}</span></div>'
    return field(name, box, label)


def text_box(name: str, st: Settings, placeholder: str = "") -> str:
    kind, extra = BY_NAME[name][2], BY_NAME[name][3]
    max_len = extra if kind in ("text", "watch") else extra[1]
    value = esc(getattr(st, name))
    if kind == "watch":
        box = (f'<textarea name="{name}" maxlength="{max_len}" spellcheck="false" '
               f'placeholder="{esc(placeholder)}">{value}</textarea>')
    else:
        box = (f'<input type="text" name="{name}" maxlength="{max_len}" value="{value}" '
               f'placeholder="{esc(placeholder)}" spellcheck="false" autocapitalize="characters">')
    return field(name, box)


def choice(name: str, st: Settings, options=None) -> str:
    return field(name, seg(name, options or BY_NAME[name][3], getattr(st, name)))


def card(title: str, body: str, status: str = "", wide: bool = False) -> str:
    status_html = f'<div class="status">{esc(status)}</div>' if status else ""
    return (f'<section class="card{" wide" if wide else ""}"><h2>{esc(title)}</h2>'
            f'{body}{status_html}</section>')


def ticks(items: str) -> str:
    return f'<div class="ticks">{items}</div>'


def tick(name: str, label: str, checked: bool, value: str | None = None, swatch: str = "",
         extra_class: str = "") -> str:
    value_attr = f' value="{esc(value)}"' if value is not None else ""
    sw = f'<i class="sw" style="background:{swatch}"></i>' if swatch else ""
    return (f'<label class="tick {extra_class}"><input type="checkbox" name="{name}"{value_attr}'
            f'{" checked" if checked else ""}>{sw}{esc(label)}</label>')


def tab(tab_id: str, intro: str, cards: str) -> str:
    return (f'<section class="tab" id="tab-{tab_id}"><p class="tab-intro">{esc(intro)}</p>'
            f'<div class="grid">{cards}</div></section>')


def render_page(st: Settings, banner: str = "", statuses: dict[str, str] | None = None,
                notice: str = "", proc_rows: list[dict] | None = None) -> str:
    """statuses: card title → status line. notice: text for the save bar.
    proc_rows: airports offered for SIDs/STARs (see SkyScope.procedure_table)."""
    statuses = statuses or {}
    proc_rows = proc_rows or []

    # --- General: location and data source ----------------------------------------
    centred = AIRPORT_INDEX.get(st.center_airport) if st.center_airport else None
    current = (f'{esc(centred["ident"])} · {esc(centred["name"])}' if centred else "")
    airport = field("center_airport",
                    f'<input type="hidden" name="center_airport" value="{esc(st.center_airport)}">'
                    f'<div class="chip" id="airport-current"{"" if centred else " hidden"}>'
                    f'<span>Centred on <b id="airport-name">{current}</b></span>'
                    '<button type="button" class="link" id="airport-clear" title="Stop following this airport">✕</button></div>'
                    '<input type="text" id="airport-search" placeholder="Search by code or name: KDVT, PHX, Heathrow..." '
                    'autocomplete="off" spellcheck="false" data-nodirty>'
                    '<div class="results" id="airport-results" hidden></div>',
                    hint="About 48,000 airports worldwide. Choosing one sets the position below.")
    location = (
        choice("location_source", st)
        + f'<div data-when="location_source=manual">{airport}</div>'
        + f'<div class="row2">{number("lat", st)}{number("lon", st)}</div>'
        + number("gps_update_s", st)
        + '<div class="buttons"><button class="secondary" type="button" id="geo" hidden>'
          "Use this computer's location</button>"
          '<button class="secondary" type="submit" formaction="/radar_config/gps-now">'
          "Read GPS now</button></div>"
          '<div class="status" id="geo-note" hidden></div>')
    data = choice("data_source", st) + text_box("sdr_location", st)
    general = tab("general", "Where the radar is centred and where its aircraft data comes from.",
                  card("Location", location, statuses.get("Location", ""))
                  + card("Aircraft data", data, statuses.get("Aircraft data", "")))

    # --- Display: units, scope, sweep ----------------------------------------------
    units = (choice("distance_unit", st) + choice("speed_unit", st) + choice("altitude_unit", st)
             + toggle("show_airspeed", st))
    ranges = [(str(i), f"{v:g}") for i, v in enumerate(st.range_presets())]
    legend = "".join(
        f'<span><i class="swatch" style="background:rgb{CLASS_COLORS[cid]}"></i>{esc(label)}</span>'
        for cid, label in CLASSES)
    scope = (
        field("range_index", seg("range_index", ranges, st.range_index),
              label=f"Range ({st.distance_symbol}, to the outer ring)")
        + choice("aircraft_symbol", st)
        + toggle("color_by_kind", st)
        + f'<div class="legend" data-when="color_by_kind=on">{legend}</div>'
        + choice("airline_logos", st)
        + toggle("show_photos", st)
        + '<div class="hint" data-when="show_photos=on">Only photos of the exact aircraft (from '
          'Planespotters.net, credited and linked); aircraft without one show "No image available".</div>'
        + toggle("show_routes", st)
        + '<div class="hint" data-when="show_routes=on">From and to airports of airline flights, by flight '
          'number (adsbdb.com), shown only when the route fits where the aircraft is. Private and VFR '
          'flights have no published route.</div>'
        + toggle("show_beyond_dots", st) + toggle("show_ground", st))
    sweep = (toggle("sweep_enabled", st)
             + f'<div class="row2">{number("sweep_period_s", st)}{number("sweep_trail_deg", st)}</div>')
    display = tab("display", "How the scope and its labels look.",
                  card("Scope", scope) + card("Units", units) + card("Radar sweep", sweep))

    # --- Map: airports, airspace, SIDs/STARs ----------------------------------------
    type_ticks = ticks("".join(tick(f"runway_types_{v}", label, v in st.runway_types)
                               for v, label in BY_NAME["runway_types"][3]))
    airports_card = (toggle("show_runways", st)
                     + field("runway_types", type_ticks,
                             hint="Major: large commercial airports. Regional: medium airports. "
                                  "Small: paved fields of 2,000 ft or more.")
                     + toggle("runway_centerlines", st))
    airspace_card = (toggle("show_airspace", st)
                     + '<div class="legend" data-when="show_airspace=on">'
                       '<span><i class="swatch" style="background:#4673d2"></i>Class B (solid)</span>'
                       '<span><i class="swatch" style="background:#a55fb9"></i>Class C (solid)</span>'
                       '<span><i class="swatch" style="background:#4673d2;opacity:.55"></i>Class D (dashed)</span></div>'
                       '<div class="hint">Each shelf is labelled ceiling/floor in hundreds of feet '
                       '(90/30 = 3,000 to 9,000 ft) when zoomed in. US only (FAA data).</div>')
    dist = lambda km: "" if km is None else f" · {st.format_distance(km)}"
    rows = ""
    for r in proc_rows:
        ident = r["ident"]
        sid_box = tick("proc_sid_" + ident, f"{r['sids']} SIDs", r["choice"] in ("sid", "both"), extra_class="sm")
        star_box = tick("proc_star_" + ident, f"{r['stars']} STARs", r["choice"] in ("star", "both"), extra_class="sm")
        rows += (f'<tr><td class="ap"><b>{esc(ident)}</b> <small>{esc(r["type"])}</small></td>'
                 f'<td class="name">{esc(r["name"])}<small>{dist(r["dist_km"])}</small></td>'
                 f'<td class="pick">{sid_box}</td><td class="pick">{star_box}</td></tr>')
    if not rows:
        rows = ('<tr id="proc-empty"><td colspan="4">No airports with published SIDs/STARs within range. '
                'Add one below, or widen the range.</td></tr>')
    procedures_card = (
        choice("procedure_mode", st)
        + '<div class="legend"><span><i class="swatch" style="background:#37b4b4"></i>SID (departure)</span>'
          '<span><i class="swatch" style="background:#d29637"></i>STAR (arrival)</span></div>'
        + field("procedure_airports",
                f'<input type="hidden" name="proc_list" value="{esc(",".join(r["ident"] for r in proc_rows))}">'
                '<div class="buttons" style="margin-top:0">Tick: '
                '<button type="button" class="link" data-tick-all="proc_sid_:1">all SIDs</button>'
                '<button type="button" class="link" data-tick-all="proc_star_:1">all STARs</button>'
                '<button type="button" class="link" data-tick-all="proc_:0">none</button></div>'
                '<div class="scroll"><table class="procs"><thead><tr><th>Airport</th><th>Name</th>'
                f'<th>Departures</th><th>Arrivals</th></tr></thead><tbody id="proc-rows">{rows}</tbody></table></div>'
                '<div class="field"><div class="label">Add another airport</div>'
                '<input type="text" id="proc-search" placeholder="Search US airports: KLAS, Tucson..." '
                'autocomplete="off" spellcheck="false" data-nodirty>'
                '<div class="results" id="proc-results" hidden></div></div>',
                hint="Airports with published procedures within reach of the scope, largest first. "
                     "US only (FAA CIFP data). Not for navigation."))
    map_tab = tab("map", "ATC-style map layers: runways, airspace and departure/arrival routes.",
                  card("Airports and runways", airports_card) + card("Airspace", airspace_card)
                  + card("SIDs and STARs", procedures_card, wide=True))

    # --- Filters --------------------------------------------------------------------
    kinds = ticks("".join(
        tick(f"class_{cid}", label, cid not in st.hidden_classes,
             swatch=f"rgb{CLASS_COLORS[cid]}" if st.color_by_kind else "")
        for cid, label in CLASSES))
    bands = ticks("".join(tick(f"band_{bid}", label, bid not in st.hidden_alt_bands)
                          for bid, label in ALT_BANDS))
    order = sorted(COUNTRY_NAMES, key=lambda c: (c not in st.country_filter, c))
    countries = "".join(tick("country", c, c in st.country_filter, value=c, extra_class="sm country")
                        for c in order)
    picked = f"{len(st.country_filter)} selected" if st.country_filter else "none selected"
    filters = tab(
        "filters", "Which aircraft appear. Watched aircraft and emergencies always show. "
                   "Save a set of filters as a preset on the Presets tab.",
        card("Kinds of aircraft",
             field("hidden_classes", kinds, label="", hint="Tick the kinds to show.")
             + '<div class="buttons"><button class="secondary" type="button" id="clear-filters">'
               "Clear all filters</button></div>")
        + card("Altitude", field("hidden_alt_bands", bands, label="",
                                 hint="Barometric altitude. Aircraft on the ground count as the lowest block."))
        + card("Types and airlines", choice("type_mode", st) + text_box("type_filter", st)
               + choice("operator_mode", st) + text_box("operator_filter", st))
        + card("Country of registration",
               choice("country_mode", st)
               + field("country_filter",
                       '<input type="text" id="country-search" placeholder="Search countries" data-nodirty>'
                       f'<div class="countries">{countries}</div>', label=f"Countries ({picked})",
                       hint="From each aircraft's ICAO address, so it works without a registration.")))

    # --- Presets ----------------------------------------------------------------------
    presets = all_presets(st)
    active = matching_preset(st)
    preset_opts = "".join(
        f'<option value="{esc(n)}"{" selected" if n == active else ""}>{esc(n)}'
        f'{"" if n in BUILTIN_PRESETS else " (yours)"}</option>' for n in presets)
    labels = dict(CLASSES)
    bands_l = dict(ALT_BANDS)

    def summary(v: dict) -> str:
        shown = [labels[c] for c, _ in CLASSES if c not in v.get("hidden_classes", [])]
        alt = [bands_l[b] for b, _ in ALT_BANDS if b not in v.get("hidden_alt_bands", [])]
        parts = ["all kinds" if len(shown) == len(CLASSES) else ", ".join(shown) or "no kinds"]
        if len(alt) < len(ALT_BANDS):
            parts.append(", ".join(alt) or "no altitudes")
        for key, what in (("type_mode", "types"), ("operator_mode", "airlines"), ("country_mode", "countries")):
            if v.get(key, "off") != "off":
                parts.append(f"{'only' if v[key] == 'only' else 'hide'} some {what}")
        return "; ".join(parts)

    preset_rows = "".join(
        f'<div class="{"on" if n == active else ""}"><b>{esc(n)}{"" if n in BUILTIN_PRESETS else " (yours)"}</b>'
        f'<span>{esc(summary(v))}</span></div>' for n, v in presets.items())
    presets_tab = tab(
        "presets", "Named sets of filters. Applying one replaces the filters on the Filters tab.",
        card("Use a preset",
             f'<div class="field"><div class="label">Preset (now: {esc(active or "custom filters")})</div>'
             f'<select name="preset" data-nodirty>{preset_opts}</select></div>'
             '<div class="buttons"><button class="secondary" type="submit" name="action" value="apply_preset">Apply preset</button>'
             '<button class="danger" type="submit" name="action" value="delete_preset">Delete</button></div>'
             '<div class="hint">Built-in presets can\'t be deleted. The radar page has a preset picker too.</div>')
        + card("Save the current filters",
               '<div class="field"><div class="label">Name</div>'
               '<input type="text" name="preset_name" maxlength="40" placeholder="e.g. Phoenix arrivals" data-nodirty></div>'
               '<div class="buttons"><button class="secondary" type="submit" name="action" value="save_preset">Save as preset</button></div>'
               '<div class="hint">Saves what the Filters tab is set to (including unsaved changes).</div>')
        + card("All presets", f'<div class="preset-list">{preset_rows}</div>', wide=True))

    # --- Alerts ------------------------------------------------------------------------
    alerts = tab("alerts", "Highlighting aircraft you care about.",
                 card("Emergencies", toggle("highlight_emergencies", st)
                      + '<div class="hint">Flashing symbol, pulsing ring and a red banner; always shown, '
                        'whatever the filters.</div>')
                 + card("Watchlist", text_box("watchlist", st, placeholder="e.g. N123AB, ENY*, B52")
                        + toggle("watch_notice", st)))

    # --- About -------------------------------------------------------------------------
    host = socket.gethostname().split(".")[0]
    address = lan_address()
    sat_where = f"{host}.local" + (f"  or  {address}" if address else "")
    centre = {"gps_once": "GPS (read once at start-up)", "gps_live": "GPS (kept up to date)"}.get(
        st.location_source, st.center_airport or f"{st.lat:.4f}, {st.lon:.4f}")
    source = "Your SDR receiver (readsb)" if st.data_source == "sdr" else "adsb.fi (internet)"
    links = "".join(
        f'<li><a href="{esc(url)}" target="_blank" rel="noopener">{esc(name)}</a><span>{esc(what)}</span></li>'
        for name, url, what in [
            ("SkyScope Guide", "/guide", "Setting up, using and installing SkyScope (web page)"),
            ("Guide as a PDF", "/docs/SkyScope-Guide.pdf", "The same guide, for printing or saving"),
            ("SkyScope on GitHub", f"{REPO}/skyscope", "Source code, updates and issues"),
            ("SkyScope Mini", f"{REPO}/skyscope-mini",
             "A standalone radar for a 4.3-inch ESP32-S3 display, no Pi needed"),
            ("SkyScope Satellite", f"{REPO}/skyscope-satellite",
             "A 4.3-inch ESP32-S3 display that mirrors this SkyScope's radar"),
        ])
    credits = "".join(f"<li>{c}</li>" for c in [
        'Aircraft positions: <a href="https://adsb.fi" target="_blank" rel="noopener">adsb.fi</a> '
        '(open data), or your own SDR receiver through readsb',
        'Airports and runways: <a href="https://ourairports.com" target="_blank" rel="noopener">OurAirports</a> '
        '(public domain)',
        "Airspace, SIDs and STARs: FAA (US public domain)",
        'Aircraft photos: <a href="https://www.planespotters.net" target="_blank" rel="noopener">Planespotters.net</a>, '
        "credited on each photo",
        'Flight routes: <a href="https://www.adsbdb.com" target="_blank" rel="noopener">adsbdb.com</a> '
        "(community data, by flight number)",
        "Country from the ICAO address: the tar1090 project's table",
        'Grew from <a href="https://github.com/MatixYo/ESP32-Plane-Radar" target="_blank" rel="noopener">'
        "ESP32-Plane-Radar</a> by MatixYo",
        'Drawn with <a href="https://www.pygame.org" target="_blank" rel="noopener">pygame</a> (LGPL) in Python',
        'Built with <a href="https://claude.com/claude-code" target="_blank" rel="noopener">Claude Code</a> (Anthropic)',
    ])
    about = (
        '<section class="tab" id="tab-about">'
        '<div class="about-head"><img src="/docs/images/moon-pi-logo.png" alt="Project Moon Pi logo">'
        f'<div><h2>SKYSCOPE</h2><div class="sub">Version {esc(VERSION)} &middot; Designed and Created by Project Moon Pi</div>'
        "<p>A live ADS-B radar scope for a Raspberry Pi and an HDMI screen, or any browser on your network: "
        "aircraft around you with a sweeping beam, runways, airspace and procedures, filters and alerts.</p>"
        "</div></div>"
        '<div class="grid">'
        + card("This SkyScope",
               '<dl class="facts">'
               f"<dt>Version</dt><dd>{esc(VERSION)}</dd>"
               f"<dt>Centre</dt><dd>{esc(centre)}</dd>"
               f"<dt>Aircraft data</dt><dd>{esc(source)}</dd>"
               f"<dt>Radar</dt><dd>http://{esc(host)}.local:{st.web_port}/radar</dd>"
               f"<dt>Satellite address</dt><dd>{esc(sat_where)} &middot; port {st.web_port}</dd>"
               "</dl>"
               '<div class="hint">Enter the Satellite address on a SkyScope Satellite\'s setup page '
               "to mirror this radar on it.</div>")
        + card("Guide and projects", f'<ul class="links">{links}</ul>')
        + card("Data and credits", f'<ul class="links">{credits}</ul>'
               + '<div class="hint">Not for navigation or air traffic control. ADS-B shows only aircraft that '
                 "broadcast it, and public feeds can be delayed or incomplete.</div>")
        + card("Licence", "<p>SkyScope is free software under the MIT licence. "
               f'See <a href="{REPO}/skyscope/blob/main/LICENSE" target="_blank" rel="noopener">LICENSE</a>.</p>'
               "<p>The Project Moon Pi name and logo belong to Project Moon Pi.</p>")
        + "</div></section>")

    nav = "".join(f'<button type="button" data-tab="{tid}">{esc(label)}</button>' for tid, label in TABS)
    body = general + display + map_tab + filters + presets_tab + alerts + about
    bar_class, state_text = "", notice or "All changes saved"
    if banner:
        bar_class, state_text = " error", "Not saved: see the message above"
    return (PAGE.replace("%%TABS%%", nav).replace("%%BANNER%%", banner).replace("%%BODY%%", body)
            .replace("%%BARCLASS%%", bar_class).replace("%%STATE%%", esc(state_text)))


class SettingsServer:
    """Runs the web page on a daemon thread. The render loop calls
    apply_pending() each frame with a function that applies a change dict."""

    def __init__(self, settings: Settings, port: int, statuses=lambda: {}, radar=None):
        self.settings = settings
        self.port = port
        self.statuses = statuses  # () → {group title: status line}
        self.radar = radar  # SkyScope app: data for the browser display at /radar
        self._pending: queue.Queue[tuple[dict, threading.Event]] = queue.Queue()
        self.stop_requested = threading.Event()  # set by /api/shutdown (the Stop SkyScope icon)

    def start(self) -> bool:
        server_ref = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # keep the console quiet
                pass

            def _send(self, body: str, status: int = 200):
                data = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _send_bytes(self, data: bytes, content_type: str, cache: str = "no-store"):
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", cache)
                self.end_headers()
                self.wfile.write(data)

            def _send_json(self, obj):
                self._send_bytes(json.dumps(obj, separators=(",", ":")).encode("utf-8"),
                                 "application/json")

            def do_GET(self):
                path = self.path.split("?")[0]
                radar = server_ref.radar
                if radar is not None:
                    if path == "/radar":
                        self._send_bytes(RADAR_PAGE.read_bytes(), "text/html; charset=utf-8")
                        return
                    if path == "/api/state":
                        self._send_json(radar.web_state())
                        return
                    if path == "/api/photo":
                        a = {k: v[0][:60] for k, v in parse_qs(self.path.partition("?")[2]).items()}
                        photo = PHOTOS.find(a.get("hex", ""), a.get("reg", ""))
                        self._send_json(photo or {})
                        return
                    if path == "/api/airports":
                        args = parse_qs(self.path.partition("?")[2])
                        q = args.get("q", [""])[0]
                        if args.get("procedures"):
                            # Only airports with published SIDs/STARs, with their counts.
                            found = []
                            for ap in AIRPORT_INDEX.search(q, 60):
                                sids, stars = OVERLAYS.counts(ap["ident"])
                                if sids or stars:
                                    found.append({**ap, "sids": sids, "stars": stars})
                            self._send_json(found[:12])
                        else:
                            self._send_json(AIRPORT_INDEX.search(q))
                        return
                    if path == "/api/satellite":  # SkyScope Satellite displays (ESP32)
                        self._send_json(radar.web_satellite())
                        return
                    if path == "/api/satellite/map":
                        self._send_json(radar.web_satellite_map())
                        return
                    if path == "/api/static":
                        self._send_json(radar.web_static())
                        return
                    m = LOGO_PATH_RE.match(path)
                    if m:
                        logo = radar.logos.file_for(m.group(1))
                        if logo is None:
                            self.send_error(404)
                        else:
                            self._send_bytes(logo.read_bytes(), "image/png", "max-age=86400")
                        return
                if path == "/guide":
                    self.send_response(302)
                    self.send_header("Location", "/docs/guide.html")
                    self.end_headers()
                    return
                m = DOCS_PATH_RE.match(path)
                if m and ".." not in m.group(1):
                    doc = DOCS_DIR / m.group(1)
                    if doc.is_file():
                        self._send_bytes(doc.read_bytes(), DOCS_TYPES[m.group(2)], "max-age=300")
                    else:
                        self.send_error(404)
                    return
                if path == "/":
                    self.send_response(302)
                    self.send_header("Location", "/radar" if radar is not None else CONFIG_PATH)
                    self.end_headers()
                    return
                if path != CONFIG_PATH:
                    self.send_error(404)
                    return
                query = self.path.partition("?")[2]
                notice = next((text for key, text in NOTICES.items() if key in query), "")
                self._send(render_page(server_ref.settings, "", server_ref.statuses(), notice,
                                       server_ref.procedure_rows()))

            def do_POST(self):
                path = self.path.split("?")[0]
                if path == "/api/shutdown":
                    # Only from this computer, and only with the launcher's header:
                    # a web page can't send a custom header to another site
                    # without permission SkyScope never gives.
                    local = self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1")
                    if not local or self.headers.get("X-SkyScope") != "stop":
                        self.send_error(403)
                        return
                    self._send_json({"ok": True})
                    server_ref.stop_requested.set()
                    return
                if path == "/api/next-range" and server_ref.radar is not None:
                    done = threading.Event()
                    server_ref._pending.put((server_ref.radar.web_next_range(), done))
                    done.wait(2.0)
                    self._send_json({"ok": True})
                    return
                if path == "/api/quick" and server_ref.radar is not None:
                    # Radar page's altitude / procedure dropdowns: {"altitude": "low"} etc.
                    length = min(int(self.headers.get("Content-Length") or 0), 1024)
                    try:
                        changes = server_ref.radar.web_quick(json.loads(self.rfile.read(length) or b"{}"))
                    except ValueError:
                        changes = {}
                    if changes:
                        done = threading.Event()
                        server_ref._pending.put((changes, done))
                        done.wait(2.0)
                    self._send_json({"ok": bool(changes)})
                    return
                if path == "/api/preset" and server_ref.radar is not None:
                    # Radar page's preset picker: body is the preset name.
                    length = min(int(self.headers.get("Content-Length") or 0), 1024)
                    name = self.rfile.read(length).decode("utf-8", "replace")
                    found = preset_changes(server_ref.settings, name)
                    if found:
                        done = threading.Event()
                        server_ref._pending.put((found, done))
                        done.wait(2.0)
                    self._send_json({"ok": bool(found)})
                    return
                if path not in (CONFIG_PATH, GPS_NOW_PATH):
                    self.send_error(404)
                    return
                length = min(int(self.headers.get("Content-Length") or 0), 65536)
                form = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
                changes, errors = parse_form(form)
                if not errors:
                    errors = apply_preset_action(form, changes, server_ref.settings)
                if errors:
                    banner = '<div class="banner err">' + "<br>".join(map(html.escape, errors)) + "</div>"
                    self._send(render_page(server_ref.settings, banner, server_ref.statuses(), "",
                                           server_ref.procedure_rows()), 400)
                    return
                if path == GPS_NOW_PATH:
                    # Save the form too, then take a fresh GPS fix. Choosing GPS
                    # here is implied if the source was still manual.
                    if changes.get("location_source") == "manual":
                        changes["location_source"] = "gps_once"
                    changes["_gps_now"] = True
                done = threading.Event()
                server_ref._pending.put((changes, done))
                done.wait(2.0)  # until the render loop has applied it
                action = (form.get("action") or ["save"])[0]
                result = "gps" if path == GPS_NOW_PATH else {
                    "apply_preset": "applied", "save_preset": "presetsaved",
                    "delete_preset": "deleted"}.get(action, "saved")
                self.send_response(303)
                self.send_header("Location", f"{CONFIG_PATH}?{result}=1")
                self.end_headers()

        try:
            httpd = ThreadingHTTPServer(("0.0.0.0", self.port), Handler)
        except OSError as exc:
            print(f"web: can't listen on port {self.port}: {exc}")
            return False
        threading.Thread(target=httpd.serve_forever, name="web", daemon=True).start()
        print(f"Settings page: http://{lan_address()}:{self.port}{CONFIG_PATH}")
        return True

    def procedure_rows(self) -> list[dict]:
        return self.radar.procedure_table() if self.radar is not None else []

    def apply_pending(self, apply) -> None:
        while True:
            try:
                changes, done = self._pending.get_nowait()
            except queue.Empty:
                return
            apply(changes)
            done.set()
