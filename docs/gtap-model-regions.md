# Geografia GTAP compatibile con i gruppi dei modelli

Il raccordo produce **61 regioni finali a partire dalle 163 regioni native GTAP Power 2023**, usando esclusivamente aggregazioni. Non si disaggrega nessuna regione e non si usano quote di PIL o altri pesi monetari.

## Cosa è stato corretto

Il foglio `GTAP_3models` del file fornito contiene 63 voci. In `Country mapping`, FRO e IMN (righe 206–207) non hanno un valore in `Common 3 GTAP models`; il loro `Common code` è già NAI. Nel raccordo operativo entrambe vengono assegnate esplicitamente a NAI, con il nome già presente nel file: Faroe Islands and Isle of Man. Si ottengono così 64 gruppi desiderati per tutti i 210 paesi elencati.

Queste due assegnazioni mancanti sono un problema di compilazione. Gli altri conflitti derivano dal diverso dettaglio territoriale dei modelli e di GTAP: una classificazione a paesi può essere corretta e tuttavia richiedere separazioni impossibili con la baseline GTAP disponibile.

## Gli accorpamenti

| Gruppi desiderati accorpati | Codice finale | Motivo territoriale |
|---|---|---|
| ASO, AFP, TWM | AFP_ASO_TWM | XOC comprende territori in ASO e AFP; XEA comprende Macao in TWM e Corea del Nord in ASO. Il legame è transitivo. |
| LAC, AGS | AGS_LAC | XNA contiene Bermuda, assegnata a LAC, e Groenlandia, assegnata ad AGS. |
| NEU, NAI | NAI_NEU | XER contiene paesi di NEU e Fær Øer/Isola di Man del gruppo NAI. |

Si mantengono interi anche i gruppi desiderati: per esempio, accorpare AFP ad ASO comporta includere l'Afghanistan, già appartenente ad AFP, nello stesso gruppo. Non si spostano singoli paesi per comodità e non si mantengono nomi che nascondano un cambiamento di perimetro.

I 64 gruppi desiderati diventano **60**: due riduzioni per la fusione a tre gruppi e una per ciascuna delle altre due fusioni. Si conserva poi **XTW — Rest of the World**, regione nativa GTAP priva di paesi rappresentati nel foglio. Questo porta il totale a **61**. XTW comprende Antarctica, Bouvet Island, British Indian Ocean Territory e French Southern Territories secondo il catalogo territoriale GTAP; attribuirla a un altro gruppo richiederebbe una scelta ulteriore, non contenuta nell'Excel.

Si applica la chiusura transitiva dei soli accorpamenti necessari. Tutte le altre distinzioni richieste sono conservate. In termini matematici è la partizione comune più dettagliata ottenibile aggregando entrambe le classificazioni. Il criterio di riduzione riguarda le incompatibilità territoriali; non si accorpano arbitrariamente regioni indipendenti.

## Copertura e limiti

- Tutti i 210 paesi del file sono associati a una sola regione nativa GTAP e a una sola regione finale.
- Tutte le 163 regioni native hanno esattamente una destinazione. La copertura è stata verificata anche contro l'indice X della baseline nativa effettivamente presente su WSP.
- I territori GTAP non elencati fra i 210 paesi rimangono nella loro regione nativa, che viene trasferita interamente al gruppo finale. Non vengono ripartiti o ignorati.
- Le appartenenze territoriali vengono dal catalogo GTAP già presente nella documentazione MARIO, copiato con hash nella cartella del raccordo. Eventuali membri senza un ISO risolto, come Sark in XER, restano comunque nel relativo aggregato GTAP indiviso.
- Il foglio desiderato riguarda GEM-E3, OPEN-PROM e GEMINI-E3. Dopo gli accorpamenti, alcune distinzioni di OPEN-PROM e GEMINI-E3 non si recuperano per semplice riaggregazione. Anche SORMAC richiede adattamenti. `regions.csv` elenca tutti i codici di ciascun modello contenuti in ogni gruppo finale, mostrando esplicitamente i casi multipli.
- La geografia è pronta come input della pipeline; non è stato generato un nuovo database né eseguito un solver per questo raccordo.

## File operativi

La copia di riferimento e i risultati sono in `Data split/Classifications/GTAP model regions`:

- `Region clusters for models.xlsx`: copia del file fornito; i dati e le classificazioni sono identici all'originale, mentre alcuni metadati interni Office sono cambiati dopo la copia su WSP. Le correzioni operative sono nei file derivati e nell'audit, preservando il riferimento comune anche per gli altri database.
- `GTAP12 region scope.json`: catalogo territoriale utilizzato.
- `gtap-models-compatible.json`: mappa eseguibile delle 163 regioni native verso le 61 regioni finali.
- `gtap-to-model-regions.csv`: stessa mappa in due colonne, leggibile da `Geography.read`.
- `countries.csv`: corrispondenza a 210 righe fra paese, gruppo desiderato, regione nativa e regione finale.
- `regions.csv`: le 61 regioni, con gruppi desiderati, regioni native e codici dei modelli coperti.
- `reconciliation.json` e `checksums.json`: metodo, correzioni, accorpamenti e hash.

La mappa eseguibile è anche in `data/geographies/gtap-models-compatible.json` della repository, affiancata da `.source.json` con provenienza e hash. Non è stata sostituita la configurazione di default delle prove a 13 regioni.

Per selezionarla in una nuova preparazione dalla baseline nativa:

```bash
python scripts/run_disaggregation.py \
  --mapping data/geographies/gtap-models-compatible.json \
  --cleaning-policy config/cleaning-policy.json \
  --intermediate-steps \
  --output build/disaggregation/model_regions_01
```

Il comando prepara i dati; non risolve il modello. Il piano di inserimento dei settori va definito separatamente. Nel worktree MARIO `codex/mrio-memory` il comportamento che prosegue dopo un fallimento è selezionabile con `on_step_failure="continue"` nel metodo `add_sectors`; la mappa geografica da sola non lo attiva. Vedere `sequential-failures-design.md`.

Per riprodurre il raccordo dai riferimenti su WSP, con `paths.local.json` o `ENTICE_DATA_ROOT` configurato:

```bash
python scripts/reconcile_model_regions.py --output build/model_regions_review
```

Il comando richiede una cartella di output nuova e permette di specificare `--workbook` e `--gtap-scope`. Non modifica i file sorgente. La prima esecuzione ha letto il file fornito su eNextGen e il catalogo presente in MARIO; gli hash dell'originale e della copia su WSP sono tracciati separatamente. Tutte le parti `xl/` del pacchetto Excel sono identiche; le differenze riguardano metadati Office, elencati in `source-copy-verification.json`. L'audit iniziale dell'originale rimane in `initial-source-audit.json`; l'audit canonico è rigenerato dalla copia su WSP. Per usarla in una nuova installazione sono sufficienti i riferimenti copiati su WSP, senza dipendere dai percorsi personali della documentazione MARIO.

## Verifiche eseguite

I test `test_model_regions.py` e `test_geography.py` danno **17 passed**. La rigenerazione da una nuova cartella usando soltanto i riferimenti copiati su WSP ha riprodotto byte per byte mappa JSON, mappa CSV, tabelle dei paesi e delle regioni. Anche l'audit canonico usa la copia condivisa ed è riproducibile. JSON e CSV producono la stessa partizione con `Geography.read`. Il file Excel originale conserva il suo hash iniziale e tutte le parti del workbook nella copia condivisa sono identiche; le variazioni dei metadati Office sono tracciate separatamente. La mappa in repository è identica alla mappa condivisa. Non è stato eseguito alcun modello economico.
