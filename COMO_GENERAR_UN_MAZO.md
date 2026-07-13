# Cómo generar un mazo de Gitster (guía para el futuro yo)

Guía completa para pasar de "mis colegas han actualizado sus playlists" a "tengo las cartas impresas y la app actualizada", asumiendo que no recuerdas nada. Cada paso dice qué hace, cuánto tarda y qué mirar.

> **La regla de oro**: lo ya impreso es intocable. El sistema nunca reimprime, renumera ni mueve cartas existentes; cada tirada solo **añade** cartas nuevas. Por eso el único momento delicado es justo antes de imprimir (paso 6): ahí es donde hay que revisar con calma.

---

## 0. Requisitos previos

- Este repo en `C:\Users\Guille\gitster`.
- Que cada jugador haya actualizado su playlist de Spotify (las URLs están en `pipeline/config/config.json`).
- `pipeline/.env` con las credenciales de Spotify (ya está; si falta, copia `.env.example` y rellena).
- Una terminal (PowerShell o Git Bash) en la carpeta `pipeline`:

```powershell
cd C:\Users\Guille\gitster\pipeline
.venv\Scripts\activate
```

Si `.venv` no existe (PC nuevo, por ejemplo):

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
```

Comprobación rápida de que todo vive: `gitster --help` debe listar los comandos `ingest / curate / build-deck / run / registry`.

### ¿Ha entrado o salido alguien del grupo?

Edita `pipeline/config/config.json` **antes** de empezar:
- **Alta**: añade su bloque a `owners` (`owner_id` en minúsculas, `owner_name` como quieres que salga en las cartas, URL de su playlist y un `color` hex libre para el marco, que solo se pinta en la cara de la canción; el dorso del QR es idéntico para todos y no lleva marco).
- **Baja**: borra su bloque. Sus canciones exclusivas dejan de entrar y su nombre desaparece de los pies de las cartas nuevas automáticamente.
- El tamaño de expansión (`deck.expansion_size`, ahora 40) y los topes de artista/álbum también viven aquí.

---

## 1. Ingesta — descargar las playlists

```powershell
gitster ingest
```

- Descarga las playlists, deduplica canciones y calcula años. Tarda unos minutos.
- La primera vez tras mucho tiempo puede abrir el navegador para autorizar Spotify: acepta y listo.
- Crea una carpeta de trabajo `runs/<fecha>_<id>/` — todos los comandos siguientes usan automáticamente el run más reciente.

**Problema típico**: si falla la autenticación, borra `data/cache/spotify_token_cache` y repite (te pedirá login de nuevo).

## 2. Curación — arreglar los años malos

```powershell
gitster curate --musicbrainz
```

- Aplica todas las correcciones históricas del global store (no se pierden nunca) y genera la plantilla de revisión.
- `--musicbrainz` consulta el año real de primer lanzamiento por ISRC (≈1 seg/canción la primera vez; después usa caché). Merece la pena: Spotify da el año del *remaster* con frecuencia.

Abre **`runs/<último>/reports/candidates_review_template.xlsx`**:

| Columna | Qué es |
|---|---|
| `year_suspect` / `suspect_reason` | TRUE = huele a año malo (álbum tipo "remaster/greatest hits", año raro para el artista, discrepancia con MusicBrainz) |
| `mb_first_release_year` / `mb_match` | El año según MusicBrainz; `diff` = no coincide con Spotify |
| `track_url` | Click para escuchar la canción |
| `year_override` | **Escribe aquí el año correcto** (manda sobre todo lo demás) |
| `ai_year` / `ai_note` | Para la auditoría con IA (ver abajo) |
| `title_display_override` / `artists_display_override` | Por si un título/artista sale feo en la carta |
| `note` | Notas libres |

**Truco IA**: la **hoja 2 ("AI_AUDIT")** del Excel contiene un prompt listo para Claude en Excel — le dices que audite solo las filas sospechosas y rellena `ai_year` + `ai_note` con evidencia. Tu `year_override` manual siempre gana sobre `ai_year`.

Cuando termines de revisar (solo hace falta mirar las sospechosas):

```powershell
gitster curate --review-xlsx "runs\<el_run>\reports\candidates_review_template.xlsx"
```

Esto guarda tus correcciones en el global store **para siempre**. Puedes repetir revisar→importar las veces que quieras.

## 3. Construir el mazo

```powershell
gitster build-deck --version <etiqueta>
```

La etiqueta nombra la tirada de impresión: `baseline-2026-07`, `alta-fulanito-2027-01`... Produce en `runs/<último>/`:

- **`renders/full_deck/print_4x3_*.pdf`** — el mazo imprimible completo (solo cartas nuevas), ordenado por expansión.
- **`reports/deck_report.html`** — el informe interactivo: KPIs, tabla, filtro por jugador, gráficas de años/dueños/artistas.
- **`reports/deck.json`** — el mazo para la app.
- Apunta las cartas nuevas al registro como **`pending`** (aún no impresas).

## 4. Revisar antes de imprimir

Abre el `deck_report.html` y mira: años raros, artistas repetidos de más, cómo queda cada expansión (chips de colores). Si algo no te gusta:

1. Corrige la curación (vuelve al paso 2) o toca el config.
2. Regenera descartando lo no impreso:

```powershell
gitster build-deck --version <etiqueta> --discard-pending
```

`--discard-pending` borra del registro solo las cartas `pending` (nunca las impresas) y vuelve a seleccionar. Itera hasta que te guste.

## 5. Imprimir

Los tres PDFs contienen **las mismas cartas**, cambia solo el orden de los dorsos según cómo imprima tu impresora a doble cara:

- `print_4x3_match.pdf` — imprimir frentes y dorsos por separado y casarlos a mano.
- `print_4x3_long.pdf` — dúplex automático volteando por el **lado largo**.
- `print_4x3_short.pdf` — dúplex automático volteando por el **lado corto**.

Consejo: imprime UNA hoja de prueba a doble cara, comprueba que el QR de detrás corresponde a la carta de delante, y entonces lanza el resto. Cartas de 65×65 mm, 12 por hoja, líneas de corte incluidas.

## 6. Confirmar la impresión (¡importante!)

Solo cuando las cartas estén físicamente impresas:

```powershell
gitster registry mark-printed --version <etiqueta>
```

A partir de aquí esas cartas quedan selladas: ningún run futuro las tocará.

## 7. Actualizar la app del móvil

```powershell
$env:GITSTER_APP_DECK_JSON_PATH = "C:\Users\Guille\gitster\app\app\src\main\assets\deck.json"
gitster build-deck --version <etiqueta> ...   # o copia a mano runs\<run>\reports\deck.json a esa ruta
```

Recompila e instala (móvil conectado por USB con depuración activada):

```powershell
cd C:\Users\Guille\gitster\app
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
.\gradlew.bat assembleDebug
& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" install -r app\build\outputs\apk\debug\app-debug.apk
```

(O ábrelo en Android Studio y dale a Run, que es lo mismo.)

> **Ojo**: no commitees el `deck.json` real — el repo es público y el mazo lleva los apodos del grupo. En git debe quedarse el placeholder; el fichero real vive solo en tu disco (aparecerá como "modified", es normal).

---

## Chuleta de comandos útiles

```powershell
gitster registry show        # cuántas cartas hay, por expansión y estado
gitster registry validate    # salud del registro (detecta deriva de identidad)
gitster run --version X      # ingest + curate + build-deck del tirón (sin revisión Excel)
```

- **Registro de impresas**: `printed_registry.csv` en tu `GITSTER_GLOBAL_STORE` (ruta en `pipeline/.env`). Hay backups automáticos en `printed_registry_backups/` antes de cada cambio.
- **Los `runs/` viejos** se pueden borrar sin miedo: todo lo permanente vive en el global store.
- Las canciones del **año en curso** se excluyen a propósito (el año impreso debe ser definitivo).
