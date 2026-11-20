# StickmanHybrid Production Catalog & Episode Directory

> Complete production registry of documentary assets, organized by media format and thematic categories.

---

## 🏛️ Long-Form Documentaries (`long_videos/`)
Horizontal 16:9 Cinema Master Renders ($1920 \times 1080$ and $2560 \times 1440$).

| Episode Slug | Title / Narrative Theme | Category | Master Output |
| :--- | :--- | :--- | :--- |
| **`antikythera`** | The Antikythera Mechanism: The 2,000-Year-Old Greek Computer | Ancient Engineering & Relics | `the_antikythera_mechanism.mp4` (1080p) |
| **`herculaneum`** | The Buried Papyrus Scrolls of Mount Vesuvius | Lost Archives & Archaeology | `herculaneum_master_1440p.mp4` (1440p/1080p) |
| **`nalanda`** | Nalanda University: The Burning of 9 Million Manuscripts | Historical Tragedies & Knowledge | `nalanda_master_1440p.mp4` (1440p/1080p) |
| **`samudragupta`**| Samudragupta: The Napoleon of Ancient India | Legendary Conquerors & Empires | `samudragupta_draft.mp4` (Motion b-roll) |
| **`strasbourg`**   | The 1518 Dancing Plague: Mass Hysteria or Ergot Poison? | Bizarre Historical Mysteries | `strasbourg_master_1440p.mp4` (1440p/1080p) |
| **`terracotta`**   | The Terracotta Army & Underground Rivers of Mercury | Imperial Tombs & Wonders | Pre-production assets & cut elements |
| **`tunguska`**     | The 1908 Tunguska Event: What Leveled 80 Million Trees? | Cosmic Cataclysms & Deep Space | `tunguska_1440p_master.mp4` (1440p Master) |
| **`ulfberht`**     | The +VLFBERH+T Mystery: Viking Crucible Steel Swords | Lost Metallurgy & Ancient Tech | `test_preview.mp4` (1080p) |
| **`yakuza`**       | Yakuza: From Post-War Black Markets to Corporate Syndicates | Underworld Syndicates & Crime | `yakuza_master_1440p.mp4` (1440p/1080p) |
| **`yasuke`**       | Yasuke: The African Samurai of Oda Nobunaga | Legendary Warriors & Feudal Japan | `final.mp4` (1080p) |

---

## ⚡ Vertical Shorts & Reels (`shorts/`)
Vertical 9:16 Portrait Fast-Paced Formats ($1080 \times 1920$ with word-synced kinetic captions).

| Short Slug | Concept / Premise | Category | Rendered Parts |
| :--- | :--- | :--- | :--- |
| **`dark_forest`**    | The Dark Forest Hypothesis: Why the Galaxy is Silent | Cosmic Paradox & Fermi Horror | Parts 1, 2, 3 (`1080x1920`) |
| **`ink_outbreak`**   | The Ink Outbreak: Autonomous Living Stain Anomaly | High-Tension Sci-Fi & Lore | Parts 1, 2, 3 (`1080x1920`) |
| **`man_from_taured`**| The Man from Taured: The Traveler from a Non-Existent State | Parallel Realities & Glitches | Parts 1, 2, 3 (`1080x1920`) |
| **`mariana_anomaly`**| The Mariana Trench Depth Ping Anomaly | Abyssal Depths & Ocean Unknown | Parts 1, 2, 3 (`1080x1920`) |
| **`project_chrono`** | Project Chronos / The Vatican Chronovisor | Vatican Secrets & Temporal Tech | Parts 1, 2, 3 (`1080x1920`) |
| **`sun5s`**          | What Happens if the Sun Vanishes for Exactly 5 Seconds? | Space Catastrophe Experiments | Full audio & animation pipeline |
| **`werewolf`**       | The Werewolf of Bedburg: The 1589 Trial of Peter Stumpp | Medieval Folklore & True Horrors | `werewolf_short.mp4`, Part 2 |

---

## 🎯 Categorical Grouping (Thematic Channels & Playlists)

### 1. 🔍 Ancient Tech, Archaeology & Lost Wonders
- `long_videos/antikythera`
- `long_videos/herculaneum`
- `long_videos/nalanda`
- `long_videos/terracotta`
- `long_videos/ulfberht`

### 2. 🌌 Cosmic Horrors, Space & Scientific Anomalies
- `long_videos/tunguska`
- `shorts/dark_forest`
- `shorts/sun5s`
- `shorts/mariana_anomaly`

### 3. 🌀 Glitches, Temporal Secrets & Creepypasta Lore
- `shorts/man_from_taured`
- `shorts/project_chrono`
- `shorts/ink_outbreak`

### 4. ⚔️ Empires, Warriors & Underworld History
- `long_videos/yasuke`
- `long_videos/samudragupta`
- `long_videos/yakuza`
- `long_videos/strasbourg`
- `shorts/werewolf`

---

## 🛠️ CLI Resolution & Usage
All Matchsticks & BOMA Director commands automatically resolve bare slugs to either directory:
```powershell
# Both commands target C:\Users\User\StickmanHybrid\long_videos\nalanda:
python matchsticks.py render nalanda
python matchsticks.py render long_videos/nalanda

# Both commands target C:\Users\User\StickmanHybrid\shorts\dark_forest:
python matchsticks.py qc dark_forest
python matchsticks.py qc shorts/dark_forest
```
