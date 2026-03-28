# claude-mem vs. palaia — Tiefenanalyse

**Datum**: 2026-03-28
**Verglichen**: claude-mem v10.6.2 (thedotmack/claude-mem) vs. palaia v2.3.3

---

## 1. Architektur-Vergleich

| Aspekt | claude-mem | palaia |
|--------|-----------|--------|
| Sprache | TypeScript / Bun | Python + TS (OpenClaw Plugin) |
| Storage | SQLite + ChromaDB (optional) | SQLite + Flat-Files (hot/warm/cold) + optional PostgreSQL |
| Embeddings | Delegiert an ChromaDB via MCP | Eigene Embedding-Chain (fastembed, Ollama, OpenAI, etc.) |
| Worker | Persistenter HTTP-Server (Port 37777) | Embed-Server (Unix Socket Daemon) |
| MCP | Thin Proxy → Worker API | Direkte Tool-Implementierung |
| Binary | 63 MB Bun-Standalone | pip install (~leichtgewichtig) |
| Lizenz | AGPL-3.0 (Core), PolyForm NC (ragtime/) | — |

### claude-mem Architektur

- **Worker-Service**: Zentraler HTTP-Server auf Port 37777, handelt alles (Capture, Search, Context, UI)
- **Hook-Driven**: Claude Code Plugin-Hooks (SessionStart, UserPromptSubmit, PostToolUse, Stop, SessionEnd) als dünne HTTP-Clients
- **Dual Storage**: SQLite (WAL, 256MB mmap, 10K page cache, FTS5) + ChromaDB (optional, Vektor-Suche)
- **SDK Observer Agent**: Separater Claude-Prozess für Memory-Extraktion (siehe Abschnitt 2)
- **MCP Server**: Thin Wrapper über Worker-API, 7 Tools (search, timeline, get_observations, smart_search, smart_unfold, smart_outline, __IMPORTANT)
- **Web Viewer**: React SPA mit SSE Live-Streaming auf dem Worker-Port

### palaia Architektur

- **Embed-Server**: Unix Socket Daemon, hält Embedding-Modell im RAM (< 500ms Queries)
- **OpenClaw Plugin**: TypeScript, agent_end + before_prompt_build Hooks
- **Flat-File + SQLite Hybrid**: Memories als Markdown-Dateien in hot/warm/cold Tiers, Metadaten + Embeddings in SQLite
- **MCP Server**: Direkte Tool-Implementierung (palaia_search, palaia_store, palaia_edit, palaia_get, palaia_list)
- **WAL-basierte Crash-Safety**: Write-Ahead-Log in SQLite für atomare Writes

### Bewertung

**claude-mem Vorteil**: Die Worker-Architektur ist konsequenter — ein einzelner persistenter Prozess handelt alles. Bei palaia sind die Zuständigkeiten verteilt (CLI, Embed-Server, OpenClaw-Plugin, MCP-Server) mit unterschiedlichen Kommunikationswegen.

**palaia Vorteil**: Kein Bun-Dependency, kein 63MB-Binary, deutlich leichtgewichtiger. Die Flat-File + SQLite Hybrid-Architektur ist transparenter (Memories als Markdown lesbar/editierbar). Die Tier-Rotation (hot/warm/cold mit Decay-Score) ist ein cleveres Aging-System, das claude-mem nicht hat.

---

## 2. Memory Capture — der kritischste Unterschied

### claude-mem: SDK Observer Agent

- Spawnt einen **separaten Claude-Prozess** via `@anthropic-ai/claude-agent-sdk`
- Observer läuft parallel zur User-Session und sieht **jede einzelne Tool-Nutzung** in Echtzeit
- Observer ist tool-less (kein Bash, Read, Write) — rein beobachtend
- Output: Strukturierte XML `<observation>` und `<summary>` Blöcke
- Observations enthalten: type, title, subtitle, facts[], narrative, concepts[], files_read[], files_modified[]
- Content-Hash-Dedup (SHA-256, 30s Fenster) verhindert Duplikate
- `<private>` Tags werden gestrippt und übersprungen
- **Kosten**: ~1 zusätzlicher API-Call pro Session

### palaia: Hook-basierte Extraktion

- `agent_end`-Hook triggert nach jedem Agent-Turn
- **LLM-basierte Extraktion** (primär): Extrahiert content, type, tags, significance aus den letzten Turns
- **Rule-Based Fallback** (wenn kein LLM verfügbar): Pattern-Matching auf Keywords (decision, lesson, surprise, commitment, correction, preference, fact)
- Significance-Threshold (default 5.0) filtert unwichtiges
- `<palaia-hint />` Tags erlauben Metadata-Injection
- Content-Hash-Dedup (permanent, nicht nur 30s)
- Injected-Context-Stripping verhindert Re-Capture von recalled Memories

### Bewertung

| Aspekt | claude-mem | palaia |
|--------|-----------|--------|
| Granularität | Jede Tool-Nutzung einzeln | Zusammenfassung am Turn-Ende |
| Qualität | Hoch (dedizierter Observer-Agent) | Gut (LLM-Extraktion), akzeptabel (Rule-Based) |
| Kosten | ~2x API-Kosten pro Session | Keine Extra-Kosten (nutzt vorhandenen Agent) |
| Offline-Fallback | Keiner (braucht API) | Rule-Based Fallback ohne LLM |
| Dedup-Fenster | 30 Sekunden | Permanent |
| Echtzeit | Ja (PostToolUse Hook) | Nein (erst am Turn-Ende) |

**claude-mem's Observer-Agent ist qualitativ überlegen** für Capture-Zuverlässigkeit. Der Observer sieht jede Tool-Nutzung in Echtzeit und komprimiert sie semantisch. palaia sieht nur eine Zusammenfassung am Ende.

**palaia's Fallback-System ist robuster** — funktioniert auch ohne API-Zugang. Die permanente Dedup ist sicherer als claude-mem's 30s-Fenster.

### Lernpotential

1. **PostToolUse-Hook nutzen**: Tool-Responses direkt als strukturierte Observations speichern, ohne LLM-Extraktion — granularer als Turn-Ende-Capture, ohne Extra-API-Kosten
2. **Leichtgewichtiger lokaler Observer**: Statt Claude-API ein kleines lokales Modell (Ollama) als Observer — Qualität zwischen Rule-Based und Full-LLM

---

## 3. Memory Retrieval & Injection

### claude-mem: 3-Layer Progressive Disclosure

1. **`search`** → Kompakter Index mit IDs (~50-100 Tokens/Result)
2. **`timeline`** → Chronologischer Kontext um eine Observation
3. **`get_observations`** → Volle Details on-demand (~500-1000 Tokens/Result)

**Suchstrategien**:
- **SQLiteSearchStrategy**: FTS5 Full-Text, Filter-only oder Fallback
- **ChromaSearchStrategy**: Vektor-Similarity gegen ChromaDB Embeddings
- **HybridSearchStrategy**: SQLite Metadata-Filter → Chroma Semantic Ranking → Intersection → Hydrate

Token-Savings: ~10x weniger Tokens als alles upfront zu laden.

### palaia: Direkte Hybrid-Injection

1. **Query Building**: Letzte User-Nachricht (+ vorheriger Turn bei < 30 Zeichen)
2. **Hybrid Search**: 0.4 × BM25 + 0.6 × Embedding Score
3. **Priority Resolution**: Per-Agent/Project Overrides, Type-Weights (process=1.5, task=1.2, memory=1.0)
4. **Context Assembly**: Kompaktes Format, max 4000 Chars, direkt als System-Context injiziert
5. **Nudge System**: Satisfaction (nach 10 Recalls), Transparency (nach 50 Recalls)
6. **Footnote Injection**: Optional `🧠` Marker mit Quellen

### Bewertung

| Aspekt | claude-mem | palaia |
|--------|-----------|--------|
| Token-Effizienz | Sehr gut (Progressive Disclosure) | Gut (festes Budget) |
| Zuverlässigkeit | Agent muss aktiv nachfragen | Automatisch, kein Agent-Handeln nötig |
| Skalierung | Gut (3-Layer bei großen Stores) | Begrenzt (4000 Chars Limit) |
| Such-Qualität | FTS5 + ChromaDB (getrennt) | BM25 + Embeddings (gewichtet, integriert) |
| UX | Agent-gesteuert | Transparent mit Nudges |

**claude-mem's 3-Layer-Ansatz skaliert besser** bei großen Memory-Stores. Der Agent entscheidet selbst, welche Details er braucht.

**palaia's Ansatz ist zuverlässiger für schwächere Agenten** — kein aktives Nachfragen nötig. Die gewichtete BM25+Embedding-Kombination ist technisch eleganter als claude-mem's getrennte Strategien.

### Lernpotential

**Zweistufiges Injection-System**:
- **Stufe 1**: Kompakte Zusammenfassungen direkt injiziert (wie bisher, aber kürzer)
- **Stufe 2**: MCP-Tools für on-demand Deep-Dive bei Bedarf
- Skaliert besser ohne die Zuverlässigkeit der automatischen Injection aufzugeben

---

## 4. Session-Handling & Context-Restoration (KRITISCH)

Dies ist der wichtigste Vergleichspunkt. Das Problem: Bei Session-Resets oder LLM-Wechseln (in OpenClaw) scheint der Agent alles zu vergessen und lädt erst nach mehreren expliziten Aufforderungen den Kontext nach.

### claude-mem: Session-Continuity

| Mechanismus | Beschreibung |
|-------------|-------------|
| **SessionStart-Hook** | Injiziert automatisch Context aus vergangenen Sessions |
| **showLastMessage** | Letzte Assistant-Nachricht der vorherigen Session als Bridge |
| **Observation-Timeline** | Alle Observations aller Sessions für das Projekt verfügbar |
| **SDK Resume** | Multi-Turn Observer-Resume über `memorySessionId` |
| **Worktree Support** | Parent-Repo + Worktree Observations werden gemergt |
| **forceInit Flag** | Verhindert stale Session-Resumption nach Crash |
| **PendingMessageStore** | Queue für Observations wenn SDK Agent nicht ready |

### palaia: Aktueller Stand

| Mechanismus | Beschreibung |
|-------------|-------------|
| **before_prompt_build** | Query-basierte Injection (abhängig von User-Nachricht) |
| **Turn-State** | In-memory Map, 5 Min TTL, nicht persistiert |
| **Kein Session-Tracking** | Keine explizite Session-Continuity |
| **Kein Last-Message-Bridge** | Kein Mechanismus für "wo waren wir?" |
| **Query-Abhängigkeit** | Bei "mach weiter" → semantisch leer → schlechte Results |

### Analyse des Problems

Wenn in OpenClaw das LLM wechselt (Fallback oder manuell), passiert:

1. Neuer Agent hat keinen Kontext der bisherigen Conversation
2. palaia's `before_prompt_build` wird getriggert
3. Die Query basiert nur auf der aktuellen User-Nachricht
4. Kurze Nachrichten wie "mach weiter" oder "ja, genau das" haben null semantischen Gehalt
5. Recall liefert irrelevante oder keine Ergebnisse
6. Der Agent wirkt, als hätte er alles vergessen
7. Erst nach expliziten Aufforderungen ("lies die Session-Files", "check Memories") lädt er nach

### Was claude-mem besser löst

1. **Session-Start Injection**: Unabhängig von der ersten User-Nachricht wird bei jedem Session-Start automatisch der letzte Kontext injiziert
2. **Last-Message Bridging**: Die letzte Assistant-Nachricht der vorherigen Session wird als Context mitgegeben → der neue Agent weiß sofort, wo er dran war
3. **Configurable Context Window**: Wie viele Observations, wie viele in Full-Detail vs. Compact

### Konkrete Lösungsvorschläge für palaia

#### Lösung 1: Session-Continuity-Layer (Höchste Priorität)

```
before_prompt_build:
  IF erster Turn nach Reset/Switch (turnStateBySession leer):
    1. Lade letzte Session-Summary (neuer Memory-Typ: "session-summary")
    2. Lade offene Tasks für dieses Projekt
    3. Injiziere als "Session Briefing" VOR der query-basierten Injection
    4. Format:
       ## Letzte Session (vor X Minuten)
       Zusammenfassung: ...
       Offene Aufgaben: ...
       Letzter Stand: ...
  ELSE:
    Normaler query-basierter Recall
```

#### Lösung 2: Automatische Session-Summaries

```
agent_end Hook:
  IF conversation hatte >= 3 Turns:
    Speichere Session-Summary als Memory (type: "session-summary")
    Inhalt: Was wurde besprochen? Was ist der aktuelle Stand? Was sind nächste Schritte?
    Tags: [auto-session, project-name]
    TTL: 7 Tage (danach in warm → cold)
```

#### Lösung 3: Context-Aware Fallback Query

```
before_prompt_build:
  IF user_message.length < 30:
    query = letzte_session_summary.content  # Nicht die User-Nachricht!
  ELIF user_message enthält Fortsetzungs-Pattern ("weiter", "ja", "mach das"):
    query = letzte_session_summary.content
  ELSE:
    query = user_message  # Normaler Pfad
```

#### Lösung 4: LLM-Switch-Detection (OpenClaw-seitig)

```
before_prompt_build:
  IF provider_changed OR model_changed:
    force_full_context_inject = true
    Injiziere:
      1. Letzte Session-Summary
      2. Letzte N Turns als Kontext
      3. Offene Tasks
      4. Aktive Projekt-Infos
```

---

## 5. UX/UI-Vergleich

| Aspekt | claude-mem | palaia |
|--------|-----------|--------|
| Installation | `/plugin marketplace add` (1 Befehl) | `pip install` + OpenClaw Config |
| Web UI | React SPA mit Live-SSE-Streaming | Keines |
| Settings | Browser-Panel + JSON | CLI + JSON |
| Sprachen | 30+ Übersetzungen | — |
| Modes | Code, Law, Email, Chill, etc. | — |
| Transparency | Token-Economics-Anzeige | Smart Nudging (Satisfaction, Transparency) |
| Memory-Inspektion | Web Viewer (Echtzeit) | Markdown-Dateien direkt lesbar |
| Privacy | `<private>` Tags, Project Exclusion | Scope-System (private/team/public) |

### Was claude-mem besser macht

- **Echtzeit-Feedback**: Web-Viewer zeigt live, was gespeichert wird → Vertrauen und Debugging
- **Token-Economics**: Zeigt Discovery-Tokens vs. Read-Tokens → Kostenverständnis
- **One-Click Install**: Plugin-Marketplace-Integration

### Was palaia besser macht

- **Smart Nudging**: Proaktive UX-Verbesserung basierend auf Nutzungsverhalten
- **Flat-File Transparency**: Memories als Markdown lesbar, editierbar, versionierbar
- **Leichtgewichtig**: Kein Browser, kein Bun, kein 63MB-Binary

### Lernpotential

- **Optionales Web-Dashboard**: Nice-to-have für Debugging und Vertrauensaufbau
- **Capture-Feedback**: Kurze Bestätigung im CLI/Chat wenn etwas gespeichert wurde (palaia macht das teilweise mit Emoji-Reactions)

---

## 6. Qualität & Zuverlässigkeit

### Robustheit

| Aspekt | claude-mem | palaia |
|--------|-----------|--------|
| Crash-Safety | Hooks non-blocking, Errors logged | WAL-basiert, atomare Writes (tmp→fsync→rename) |
| Dedup | Content-Hash, 30s Fenster | Content-Hash, permanent |
| Process Management | ProcessRegistry, Zombie Prevention, Orphan Reaper | PID-File, Advisory Locks |
| Concurrent Agents | Limit (default 2) | Per-Agent Workspace Isolation |
| Context Loop Prevention | — | Injected-Context-Stripping |
| Stale Detection | — | Embed-Server prüft alle 30s |

### Bekannte Probleme (claude-mem)

- Observation-Duplikation (Regressionen dokumentiert)
- Windows-spezifische Issues (PowerShell, Pfade, Bun Cleanup)
- Session-ID-Management-Komplexität
- Memory Leaks (untersucht, dokumentiert)
- Orphaned Process-Akkumulation
- Monolithische Dateien: SessionStore.ts (88KB), worker-service.ts (49KB), SearchManager.ts (69KB)

### Code-Qualität

| Aspekt | claude-mem | palaia |
|--------|-----------|--------|
| Tests | ~60+ Test-Files | — |
| Logging | Strukturiert mit Component-Tags | — |
| Error Handling | Defensiv, nie blockierend | WAL-Recovery, Lock-basiert |
| Architektur-Schulden | Monolithische Store/Worker/Search | Verteilte Zuständigkeiten |

---

## 7. Zusammenfassung: Top-Erkenntnisse

### Was claude-mem besser macht

1. **Session-Continuity**: Automatische Context-Injection bei Session-Start, Last-Message-Bridge
2. **Capture-Granularität**: PostToolUse-Hook erfasst jede Tool-Nutzung einzeln
3. **Progressive Disclosure**: 3-Layer Token-effizientes Retrieval
4. **Echtzeit-UI**: Web-Viewer für Debugging und Vertrauen
5. **Konsequente Worker-Architektur**: Ein Prozess für alles

### Was palaia besser macht

1. **Kein Extra-API-Cost**: Capture ohne separaten Observer-Prozess
2. **Offline-Fallback**: Rule-Based Capture ohne LLM
3. **Tier-Rotation**: Intelligentes Aging (hot/warm/cold mit Decay-Score)
4. **Flat-File Transparency**: Memories als Markdown lesbar/editierbar
5. **Integrierte Hybrid-Suche**: BM25 + Embeddings gewichtet statt getrennt
6. **Smart Nudging**: Proaktive UX-Verbesserung
7. **Scope-System**: Multi-Agent Access Control (private/team/public)
8. **WAL Crash-Safety**: Robustere Persistenz
9. **Leichtgewichtig**: Kein Bun, kein 63MB-Binary

---

## 8. Action Items für palaia (priorisiert)

### P0: Session-Continuity-Layer (KRITISCH)

**Problem**: Bei Session-Reset/LLM-Switch vergisst der Agent alles.
**Lösung**: Bei erstem Turn einer neuen Session automatisch den letzten Kontext injizieren, unabhängig von der User-Query.

**Implementierung**:
1. Neuer Memory-Typ `session-summary` — automatisch bei `agent_end` gespeichert
2. Session-Detection in `before_prompt_build`: Wenn kein Turn-State existiert → Session-Briefing injizieren
3. Last-Message-Bridge: Letzte Assistant-Nachricht der vorherigen Session als Context
4. Fortsetzungs-Pattern-Detection: "mach weiter", "ja", "genau" → Session-Summary als Query statt User-Nachricht

### P1: Granularere Capture via PostToolUse

**Problem**: Turn-Ende-Capture verliert Granularität.
**Lösung**: Tool-Nutzungen einzeln erfassen (ohne Extra-API-Kosten).

**Implementierung**:
1. Neuer Hook `post_tool_use` (oder OpenClaw-Äquivalent)
2. Tool-Responses direkt als strukturierte Observations speichern
3. Kein LLM nötig — strukturiertes Parsing der Tool-Responses
4. Am Turn-Ende: Aggregation der Tool-Observations in Session-Summary

### P2: Progressive Disclosure für große Memory-Stores

**Problem**: 4000-Char-Budget skaliert nicht bei wachsendem Store.
**Lösung**: Zweistufiges System.

**Implementierung**:
1. Stufe 1: Kompakte Zusammenfassungen direkt injiziert (kürzer als bisher)
2. Stufe 2: MCP-Tools für on-demand Deep-Dive
3. Dynamisches Budget basierend auf Store-Größe und Query-Relevanz

### P3: LLM-Switch-Detection

**Problem**: OpenClaw-seitiger Provider-Wechsel wird nicht erkannt.
**Lösung**: Provider-Change-Flag in `before_prompt_build`.

**Implementierung**:
1. OpenClaw liefert `provider_changed` Flag im Hook-Context
2. Bei Change: Force Full-Context-Inject (Session-Summary + Tasks + Projekt-Infos)
3. Optional: "Handoff-Nachricht" an neuen Agent mit Kontext-Zusammenfassung
