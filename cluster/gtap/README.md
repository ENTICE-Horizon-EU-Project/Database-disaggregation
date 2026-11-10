# Test GTAP Power 2023 sul CFDHub

I due job misurano se MARIO e CVXLab riescono a costruire, risolvere e salvare una disaggregazione monetaria ENTICE in **un unico problema**. Usano la stessa formulazione quadratica, HiGHS per la fattibilità e Clarabel per l'ottimizzazione. Non richiedono una licenza commerciale. Il ricalcolo dei conti ambientali E è differito come nel caso Mining di riferimento.

| Caso | Regioni | Attività aggiunte | Inventari | Settori finali attesi |
| --- | ---: | ---: | ---: | ---: |
| `reduced` (predefinito) | 13 | 17 Mining | 221 | 93 |
| `full` | 163 | 67 ENTICE | 10.921 | 143 |

Entrambi partono da 76 settori GTAP. Il full usa il perimetro a 67 con il PCP originario. Esegue simultaneamente tutte le attività, anche se il workbook contiene il vecchio piano a gruppi. I due job sono indipendenti.

## Ambiente e directory locale sul cluster

Servono un solo ambiente Conda e una directory locale per i dati. Sul nodo di installazione, dalla radice del checkout:

```bash
git clone --branch cluster/gtap-cfdhub --single-branch https://github.com/ENTICE-Horizon-EU-Project/Database-disaggregation.git
cd Database-disaggregation
export PIP_SRC="$PWD/../gtap-code"
conda env create -f cluster/gtap/environment.yml
conda activate gtap-cfdhub
```

Il file [environment.yml](environment.yml) installa **Database disaggregation** dal checkout corrente, compresi preparazione, riconciliazione, esportazione e analisi. Installa **MARIO** e **CVXLab** come checkout Git modificabili, alle due revisioni registrate nel file. Con `PIP_SRC` i loro sorgenti sono in `../gtap-code/mariopy` e `../gtap-code/cvxlab`. Conservare i tre checkout finché si usa l'ambiente. L'installazione iniziale usa GitHub, conda-forge e PyPI. Il calcolo usa codice e dati locali.

Copiare i due archivi interni e il file `SHA256SUMS` da **`Data split/CFDHub/20261110 - GTAP/`** all'area di trasferimento autorizzata. Sostituire i due percorsi seguenti con quelli del cluster. Mantenere `ENTICE_DATA_ROOT` anche nell'ambiente del job.

```bash
export ENTICE_DATA_ROOT="/percorso/locale/entice"
ARCHIVI="/percorso/locale/trasferimento"
mkdir -p "$ENTICE_DATA_ROOT"
(cd "$ARCHIVI" && sha256sum -c SHA256SUMS)
unzip -q "$ARCHIVI/entice-sources.zip" -d "$ENTICE_DATA_ROOT"
unzip -q "$ARCHIVI/gtap-inputs.zip" -d "$ENTICE_DATA_ROOT"
(cd "$ENTICE_DATA_ROOT" && sha256sum --quiet -c entice-sources.sha256)
python cluster/gtap/run.py reduced --check-workflow
python cluster/gtap/run.py full --check-inputs
```

| Percorso sotto `ENTICE_DATA_ROOT` | Contenuto |
| --- | --- |
| `Database/_GTAP Power 2023/` | Archivio originale CSV, cache Parquet nativa e output GTAP |
| `Data collection/Final/` | Template partner, valore aggiunto, strutture di costo, target e scambi Purdue |
| `Inventories/D2.4 inventories/` | Inventari di riferimento, input MARIO originali e 67 inventari rigenerati |
| `Classifications/` | Classificazioni e concordanze di progetto |
| `gtap-inputs/{reduced,full}/` | Baseline Parquet e workbook esatti per i due benchmark |

Il controllo del flusso stampa i percorsi dei tre moduli importati, verifica la disponibilità dei solver, risolve le fonti con l'API del progetto e controlla gli input del benchmark. I due test accettano anche `--data-root /percorso/locale/entice`. Per un mount separato dei soli input preparati si può aggiungere `--inputs /percorso/gtap-inputs`. Nella configurazione del branch i percorsi dei dataset sono relativi alla radice locale.

## Rigenerazione degli input ENTICE

Dallo stesso ambiente e con lo stesso `ENTICE_DATA_ROOT`, questo comando esegue la preparazione completa delle 67 attività: legge la baseline nativa, riconcilia profili e target, verifica i budget per settore padre e scrive baseline, workbook e audit in una directory nuova.

```bash
python scripts/run_disaggregation.py --mapping data/geographies/gtap163.json \
  --cleaning-policy config/cleaning-policy.json --output build/nuova-preparazione-163
```

Usare `data/geographies/gtap13.json` e una nuova directory per preparare le 67 attività sulla geografia aggregata. Il benchmark ridotto fornito usa lo specifico gruppo di 17 attività Mining. Le prove cronometrate leggono sempre i file preparati identificati in [inputs.json](inputs.json). La rigenerazione è un esperimento separato e scrive un audit proprio.

## Lancio

Dalla radice del checkout, nell'ambiente attivo, eseguire **un comando per allocazione**. Usare il primo per il collaudo e il secondo sul nodo ad alta memoria.

```bash
python -u cluster/gtap/run.py reduced
```

```bash
python -u cluster/gtap/run.py full
```

Ogni avvio stampa la propria cartella sotto `build/cfdhub/`. Per salvare modello, log di validazione e database sullo scratch del job, aggiungere `--output-root /percorso/scratch/risultati`. Il job scheduler può raccogliere stdout e stderr. Il nodo deve avere spazio per i file di lavoro CVXLab e l'eventuale database finale. La memoria e lo spazio richiesti dal full sono da misurare.

## Lettura del risultato

- **`run.json`** registra perimetro, versioni, opzioni, stato e fase, tempi di parete e picco RSS del processo Python in MiB. La fase di soluzione comprende fattibilità, compilazione numerica e ottimizzazione. Il tempo del solver riportato da CVXPY è disponibile in `solution[].solver_seconds`.
- **`run.prof`** è il profilo cumulativo cProfile leggibile con SnakeViz. **`profile.txt`** contiene la tabella ordinata per tempo cumulativo a fine esecuzione. Per esplorare il profilo, copiare il file su una macchina con SnakeViz ed eseguire `snakeviz /percorso/run.prof`. Il job di calcolo gira senza interfaccia grafica.
- **`model/`** conserva gli input e la diagnostica del problema generato. **`database/flows/`** contiene il risultato monetario dopo la validazione. Il launcher dichiara `success` solo dopo i controlli del solver, la verifica delle classificazioni e l'esportazione.
- Un'eccezione Python dà un codice di uscita diverso da zero e lascia fase, errore e profilo su disco. In caso di terminazione forzata controllare anche l'esito e il consumo di memoria registrati dallo scheduler. Con SIGKILL possono rimanere lo stato `running`, il profilo delle fasi completate e file parziali. Durante le fasi lunghe il launcher salva anche `current-phase.prof` ogni 60 secondi, appena Python riprende il controllo. Questo profilo parziale si può aprire con SnakeViz.

Il risultato esportato si riapre tramite `database_disaggregation.workflow.load_database(directory)`, che verifica le impronte delle matrici e conserva X indipendente. `workflow.build_dashboard(directory, output_html)` genera il dashboard HTML dallo stesso risultato.

## Provenienza degli input

Il full usa la baseline preparata e il workbook sorgente integrale del trial `20261021_gtap163_mcu_chr_01/prepared`. La copia condivisa del workbook completo si chiama `source_add_sectors.xlsx` nel pacchetto `20261021 2205 - 163 regions and 2 sectors`. Il vecchio pilot si fermò a due attività prima del solver. Il nuovo archivio conserva i byte del workbook originale della preparazione.

Il ridotto usa la baseline e il `step_add_sectors.xlsx` dello step Mining accettato in `20261020/quadratic_deferred_E/checkpoints/001_Mining`, pubblicato come `20261020 2209 - 13 regions and 17 sectors`. Il nuovo benchmark usa questi input per una soluzione indipendente. I digest dei singoli file, le attività e la copertura verificata sono in [inputs.json](inputs.json).
