# KL: pulizia post-solver e revisione economica separata

23 ottobre 2026 — CHR, estrazione di cromo, 49 regioni e 77 settori totali
(76 iniziali e un nuovo settore). Il database è stato salvato recuperando il
punto MOSEK già disponibile, con **zero nuove ottimizzazioni**.

## Regola attuale

Il solver mantiene la propria funzione obiettivo KL e i propri vincoli.
Dopo uno stato `optimal`, MARIO pulisce i risultati e li salva. Non esistono
soglie in dollari che blocchino correzioni o residui contabili in questa modalità.
Gli scarti vengono esposti alla revisione economica successiva.

La configurazione è `config/model-trials/kl-postprocess.json`, con:

```json
"solution_cleanup": "postprocess"
```

Internamente viene registrata come `{"validation": "report_only"}`. Il vecchio
esperimento con tetti di 1.000/10.000 USD rimane riproducibile nella sua
configurazione storica; i suoi tetti non si applicano a questa esecuzione.

## Come viene eseguita la pulizia

1. Si conserva il punto grezzo e lo stato originale del solver.
2. Si azzerano i negativi vietati di Z e delle componenti non negative di V.
   Tax/TTM nette mantengono il segno; Y mantiene il dominio del proprio prior,
   compresi i valori legittimamente negativi. Gli zeri strutturali sono ripristinati.
3. Si rivalutano l'obiettivo e tutti i vincoli, poi si ricostruisce il database
   attraverso il normale percorso MARIO/CVXLab.
4. I controlli monetari di bilancio e riaggregazione restano nel rapporto,
   con il loro risultato reale, anche quando non rispettano la vecchia precisione.
   Non vengono trasformati artificialmente in controlli superati.
5. L'output riporta `postprocessed_pending_review`, `residuals_enforced=false`
   ed `economic_review=pending`. Lo stato `optimal` resta attribuito al punto
   restituito dal solver; non certifica il punto modificato dalla pulizia.

Gli stati diversi da `optimal` rimangono distinti. Restano bloccanti i problemi
tecnici di ricostruzione: dati non finiti, coordinate incompatibili, impossibilità
di allineare i risultati agli input. Nel risultato storico descritto qui X, EY
e VY non sono stati modificati; E rimane da ricalcolare. Dal 28 ottobre la
regola standard dei modelli MRIO nominati include anche i residui monetari
di X e VY come diagnostica; EY mantiene il controllo non monetario.

## Risultato misurato

| Indicatore | Valore |
| --- | ---: |
| Nuove chiamate a solver | **0** |
| Stato originale MOSEK | optimal |
| Obiettivo KL dopo pulizia | Finito |
| Operandi negativi rimasti nell'entropia | 0 |
| Celle corrette | 99,266 |
| Somma delle correzioni assolute | 518,412.11 USD |
| Correzione massima per cella | 10,006.98 USD |
| Residuo massimo di riga, al netto dell'accounting ereditato | 29,709.03 USD |
| Residuo massimo di colonna, al netto dell'accounting ereditato | 24,437.12 USD |
| Scarto massimo sui trade con target attivo | 5,361.26 USD |
| Tempo della ricostruzione con audit | 153.59 s |
| Picco footprint della sola ricostruzione | 1.75 GiB |

L'ottimizzazione originale aveva richiesto circa 34,66 secondi di MOSEK e un
picco di 8,70 GiB nell'intera esecuzione. Il dato RAM della ricostruzione non è
una nuova misura della RAM necessaria per risolvere KL. Non sono stati provati
altri settori, altre dimensioni o un diverso obiettivo.

La correzione massima riguarda Capital di CHR nella regione WL, circa 10.007 USD.
Il totale delle correzioni vale circa 518.412 USD. Le differenze sui flussi netti
Tax/TTM dovute alla pulizia sono nulle. Tutti gli zeri strutturali verificati sono
esattamente zero e Capital/Labor non hanno valori negativi nei settori coinvolti.

I massimi residui relativi sulle sole celle con output positivo sono circa
0.00645% sulle righe e
0.01298% sulle colonne.
Le celle a output zero vanno valutate separatamente: per CHR in Indonesia resta
circa 15.198 USD di input netto. Il risultato viene comunque salvato e il caso
rimane evidenziato per la revisione.

Gli scarti massimi dopo riaggregazione sulla baseline sono:

| Matrice | Scarto massimo per cella, USD |
| --- | ---: |
| Z | 9,707.63 |
| Y | 23.46 |
| V | 10,006.98 |
| X | 0.00 |

I file della baseline e i target non sono stati cambiati. La riaggregazione dei
flussi ottimizzati/ripuliti è approssimata e viene misurata nella tabella.
Gli output imposti sono preservati a precisione di macchina.

I target commerciali attivi sono 157 coppie bilaterali. Come nel modello
preesistente, `Trade_selector=0` esclude molte osservazioni nulle/assenti dal
vincolo: i loro flussi non vanno descritti come trade fissati. Questa convenzione
non è stata cambiata e resta un elemento della revisione economica.

## Codice modificato

- **MARIO**: `solution_cleanup="postprocess"` esegue la proiezione dei domini e
  conserva la diagnostica senza usare soglie monetarie come motivo di rifiuto.
  I controlli di ricostruzione registrano separatamente qualità economica e
  riuscita tecnica dell'esportazione.
- **MARIO**: un contesto di recupero, esplicito e limitato a un singolo step,
  ricarica un punto grezzo già risolto. Prima verifica CSV identici byte per byte,
  contenuto dei template Excel e script del modello, insiemi e coordinate delle
  variabili. Vengono esclusi soltanto i metadati del documento Excel
  (`docProps/core.xml`), perché cambia il timestamp anche a contenuto identico.
  Il punto viene caricato con CVXPY, senza chiamare un solver, quindi attraversa
  la stessa pulizia, diagnostica ed esportazione dei risultati di una nuova run.
- **Database disaggregation**: configurazione dedicata e opzione CLI
  `--saved-solution`; provenance esplicita nel manifest. La pubblicazione
  conserva il recupero, i punti e le correzioni e indica la revisione pendente.
- **CVXLab**: nessuna modifica. Non è stato aggiunto un secondo modello,
  né una minimizzazione quadratica per correggere i bilanci.

La prima ricostruzione si è fermata prima di caricare il punto perché confrontava
anche il timestamp interno del template Excel. È stata verificata l'identità
integrale di celle e formule e il controllo è stato corretto. Anche quel tentativo
non ha eseguito ottimizzazioni; log e manifest rimangono conservati.

## Verifiche e integrità

- 146 test MARIO e 5 test della pubblicazione passati. I test coprono pulizia
  senza tetto economico, segni ammessi, dati non finiti, stati non-optimal,
  riaggregazione diagnostica e recupero senza chiamare un solver. Coprono anche
  l'esclusione dei soli metadati Excel e il rifiuto di celle/formule cambiate.
- Tutti i 24 CSV sono identici a quelli della precedente ottimizzazione CHR49.
- I valori grezzi ricaricati coincidono esattamente, variabile per variabile,
  con quelli restituiti originariamente da MOSEK.
- Le funzioni dell'obiettivo e della preparazione dei prior sono state confrontate
  con i sorgenti esattamente eseguiti nella run originale: nessun cambiamento.
- Baseline, workbook e punto originale sono hash-verificati inalterati.
- I valori SQLite esportati coincidono esattamente con il punto ripulito.
  I Parquet finali sono stati riletti e il checkpoint pubblicato viene ricaricato.
- L'obiettivo rivalutato è finito; gli scarti rispetto alla vecchia precisione
  restano registrati, senza bloccare il salvataggio.

## Dove si trovano i risultati

- [Database: 49 regioni e 77 settori](</Users/lorenzorinaldi/Library/CloudStorage/OneDrive-SharedLibraries-WSPO365/RCD-Entice-EXT - Documents/General/2.Deliverables and Milestones/WP2. Improved data and empirics on trade and climate/Data split/Database/D2.8/20261023 1404 - 49 regions and 1 sectors>).
- [Input MARIO abbinati](</Users/lorenzorinaldi/Library/CloudStorage/OneDrive-SharedLibraries-WSPO365/RCD-Entice-EXT - Documents/General/2.Deliverables and Milestones/WP2. Improved data and empirics on trade and climate/Data split/Inventories/D2.8 inventories/20261023 1404 - 49 regions and 1 sectors>).

I dettagli sono in `diagnostics/postprocess/`: audit dei vincoli e delle
correzioni, punti grezzo/ripulito, confronto economico, log, configurazioni,
sorgenti e input esatti e checksum. Il bundle `exact-inputs.zip` include anche
il punto originale e il database delle coordinate sotto `cvxlab/`, per poter
usare `--saved-solution` dopo averlo estratto. Le cartelle e i rapporti delle prove
precedenti restano invariati. Il codice rimane locale sul branch `codex/mrio-memory`.

## Riproduzione

Per una nuova ottimizzazione, usare la configurazione `kl-postprocess.json`
nel consueto comando di trial. Per recuperare il punto già esistente:

```bash
python scripts/run_model_trial.py \
  --prepared build/memory-study/49/prepared \
  --output build/model_trials/new-empty-folder \
  --options config/model-trials/kl-postprocess.json \
  --solver MOSEK \
  --saved-solution /path/to/original/cvxlab/mario_add_sector_split \
  --stop-after-step 'Memory probe'
```

Il parametro `--saved-solution` abilita soltanto il recupero verificato; senza
questo parametro la pipeline esegue normalmente l'ottimizzazione. Gli input
devono essere quelli del punto originale e l'output deve essere una cartella nuova.


## Aggiornamento del 28 ottobre: anche quadratica e checkpoint

La post-elaborazione senza soglie monetarie è ora automatica per tutti i
modelli MRIO nominati che restituiscono `optimal`, non soltanto per la
configurazione KL esplicita. Si applica anche ai controlli monetari dopo
la ricostruzione e ai budget del runner delle prove. Non cambia la formulazione
o lo stato del solver. Vedi [il rapporto a 49 regioni](qp49-order-and-numerical-acceptance.md).
