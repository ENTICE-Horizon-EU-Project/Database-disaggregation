> Historical bounded experiment. The current post-processing policy removes monetary rejection cutoffs; see [the updated report](kl-postprocessing.md).

# KL/MOSEK con pulizia numerica controllata — CHR, 13 e 49 regioni

23 ottobre 2026. Due ottimizzazioni MRIO, entrambe sul solo nuovo settore CHR
(estrazione di cromo), con 76 settori di partenza e 77 dopo lo split previsto.
Nessun passaggio a quadratica, nessun fallback e nessun test a 163 regioni.

## Esito

Il caso a **13 regioni produce un database approssimato dopo pulizia**. Il caso a
**49 regioni non è accettato con lo stesso budget numerico**: la procedura salva
il punto grezzo e le correzioni proposte, senza applicarle né esportare un database.
La successiva simulazione della pulizia a 49 regioni è solo un calcolo sul punto
salvato, non un'altra ottimizzazione e non un risultato accettato.

| Indicatore | CHR, 13 regioni | CHR, 49 regioni |
| --- | ---: | ---: |
| Esito | Accettato con pulizia | Non accettato |
| Obiettivo KL prima della pulizia | Non finito | Non finito |
| Obiettivo KL dopo pulizia | Finito | Pulizia non applicata al modello |
| Massima correzione per cella, USD | 456.72 | 10,006.98 |
| Somma delle correzioni proposte, USD | 35,182.68 | 518,412.11 |
| Massimo residuo di riga dopo pulizia, USD | 8,660.85 | 29,709.03 (simulato) |
| Massimo residuo di colonna dopo pulizia, USD | 6,159.06 | 24,437.12 (simulato) |
| Massimo scarto sui trade con target attivo, USD | 2,083.11 | 5,361.26 (simulato) |
| Tempo MOSEK, secondi | 3.21 | 34.66 |
| Tempo pipeline, secondi | 29.79 | 198.79 |
| Picco physical footprint, GiB | 0.97 | 8.70 |
| Picco RSS, GiB | 1.06 | 3.32 |

I tempi e la RAM sono misure di una singola esecuzione per dimensione, comprensive
della diagnostica. Il limite di 10 GiB non ha interrotto le prove. La RAM a 49
regioni riguarda **un solo nuovo settore**, non tutti i 67. Non basta per una nuova
stima affidabile del caso a 163 regioni o del caso simultaneo con tutti i settori.

## Cosa è cambiato e dove

### MARIO: trattamento del punto restituito e criteri di accettazione

Il modello KL, i vincoli, i pesi e le impostazioni di MOSEK rimangono quelli della
prova con filtro dei prior. Le tolleranze date al solver non sono state allentate.
Il controllo affine preliminare continua a usare Gurobi; l'obiettivo KL è risolto
con MOSEK. CVXLab non è stato modificato.

È stata aggiunta l'opzione sperimentale `split_model_options.solution_cleanup`,
disattivata per default. La configurazione di queste due prove è:

```json
"solution_cleanup": {
  "max_cell_adjustment": 0.001,
  "absolute_tolerance": 0.01,
  "relative_tolerance": 1e-8
}
```

Le unità monetarie originali sono M USD: quindi il tetto è **1.000 USD per cella**,
e il budget dei residui è **10.000 USD assoluti + 1e-8 × riferimento**. Questo è
un budget di accettazione del risultato approssimato; non è una nuova tolleranza
del solver né un criterio economico universale. I controlli storici erano
1 USD assoluto + la stessa componente relativa.

1. Il punto grezzo viene conservato integralmente con la sua diagnostica.
2. `split_solution.py` propone la proiezione sui domini di segno e sugli zeri
   strutturali. I negativi vietati di Z e Capital/Labor vengono azzerati. Y
   conserva il dominio del proprio prior, anche quando può essere negativa;
   Tax/TTM restano grandezze nette con segno. Le loro componenti ausiliarie
   rispettano i rispettivi domini e zeri.
3. Tutte le correzioni sono preparate prima di assegnare valori. Se una sola
   supera il tetto, non viene applicata nessuna correzione al modello.
4. Sul punto ripulito si rivalutano l'obiettivo KL e **tutti** i vincoli espliciti
   e i domini impliciti. Non si sostituisce l'infinito con un valore artificiale.
5. I controlli successivi alla ricostruzione e quelli di riaggregazione monetaria
   usano il budget esplicito. X resta soggetta ai controlli stretti originali;
   anche i controlli di segno restano stretti. E resta da ricalcolare.
6. Il risultato registra `approximate_after_cleanup` e conserva anche il numero
   di violazioni secondo la vecchia precisione, senza attribuire alla soluzione
   ripulita un certificato di ottimalità KL.

I cambiamenti sono in `mario/ops/split_model.py`, nel nuovo
`mario/ops/split_solution.py`, nei controlli di `add_sector_steps.py` e nella
documentazione del metodo. Non c'è un secondo modello di ottimizzazione per
riparare i bilanci: il post-processing non esegue una minimizzazione quadratica.

Una correzione aggiunta dopo il test a 13 regioni assicura inoltre che un eventuale
rifiuto dopo la pulizia non sovrascriva il punto grezzo con quello ripulito. Non
cambia il risultato accettato a 13 regioni. Gli archivi dei sorgenti eseguiti
conservano le versioni esatte di entrambe le prove.

### Database disaggregation: configurazione, pubblicazione e audit

`config/model-trials/kl-prior-floor-cleanup.json` abilita esplicitamente questa
prova. `shared_runs.py` conserva ora gli audit, i punti grezzo/ripulito e i residui,
e segnala la validazione approssimata nei README e in `run.json`. I dati rimangono
su Data split; il codice della pipeline rimane nella repository dedicata.

### CVXLab

Nessun cambiamento: i sorgenti caricati coincidono con quelli della precedente
prova con filtro dei prior. Si continua a usare la pipeline MARIO → CVXLab →
CVXPY → MOSEK e la successiva ricostruzione MARIO.

## Quanto cambiano i dati nel caso a 13 regioni

Le 5.889 celle corrette sommano circa 35.183 USD di variazioni assolute:
21.005 USD in Z_use, 13.527 USD in Z_supply, 636 USD in Y e 14,50 USD in V.
Tax/TTM nette non sono modificate dalla pulizia. Tutti gli zeri strutturali
rimangono esattamente zero e non restano operandi negativi nell'entropia.

Il totale di una riga cambia al massimo di 4.462 USD e quello di una colonna di
5.601 USD. Per CHR in Oceania, la correzione della riga vale 0,0144% di circa
30,9 milioni USD di output e riduce il residuo da 5.930 a 1.468 USD.

I file baseline e i target di input sono inalterati, verificati tramite hash.
**La riaggregazione del nuovo database sulla baseline è invece approssimata**:
il massimo scarto è circa 1.385 USD per Z, 10,71 USD per Y e 7,26 USD per V.
X riaggregata è identica alla baseline e gli output imposti restano preservati
(a precisione di macchina nel confronto con il CSV riscalato).

Non tutti i piccoli scarti assoluti sono piccoli in percentuale. Nella colonna
OXT di Rest of the World un residuo di circa 1.688 USD vale circa 0,192% dell'output.
CHR negli USA ha output zero: dopo pulizia resta un residuo di input di circa
1.761 USD, ammesso dal budget assoluto della prova. Questo non va descritto come
un bilancio esatto. I CSV di audit permettono di identificare tutti questi casi.

Il criterio storico continua a segnalare 6.345 celle di vincolo/dominio oltre
precisione, anche dopo pulizia. Il nuovo budget le accetta come residui numerici
esplicitamente dichiarati. La finitezza dell'obiettivo e l'accettazione pratica
non dimostrano da sole la bontà economica di tutte le tecnologie risultanti.

## Perché il caso a 49 regioni non è accettato

La correzione maggiore proposta riguarda Capital di CHR nella regione WL:
circa 10.007 USD. Z_use richiede correzioni fino a circa 9.708 USD per cella.
La somma proposta è circa 518.412 USD, su 99.266 celle. Questi importi superano
il tetto di 1.000 USD per cella; la routine ha quindi lasciato il punto grezzo
inalterato e non ha generato un checkpoint accettato.

La simulazione successiva sui dati salvati mostra residui fino a 29.709 USD sulle
righe e 24.437 USD sulle colonne. I massimi residui relativi, limitati alle celle
con output positivo, sono circa 0,00645% sulle righe e 0,01298% sulle colonne.
Ci sono però colonne a output zero: per esempio CHR in Indonesia lascerebbe
circa 15.198 USD di input netti. Le percentuali sui soli output positivi non
riassumono questi casi.

Quindi questo risultato non dimostra un problema economicamente enorme; dimostra
che il medesimo budget scelto per il test a 13 regioni non basta. Non sono state
rilanciate prove per aumentare automaticamente le soglie o per cambiare solver,
obiettivo, settori, target o scala. Le correzioni simulate non sono un database
pubblicato e non hanno superato la verifica completa del modello ricostruito.

## Attenzione al significato dei target commerciali

I confronti di trade del rapporto riguardano le osservazioni con
`Trade_selector=1`: 60 celle bilaterali a 13 regioni e 157 a 49 regioni.
Il codice preesistente usa `Trade_selector=0` anche per molte osservazioni nulle
oppure assenti, non solo per le celle domestiche: quelle coppie non hanno un
target vincolante. La loro conservazione esatta non va dedotta dal solo rispetto
dei target attivi. In particolare, nel risultato a 13 regioni una coppia senza
target attivo arriva a circa 27,24 milioni USD; non è generata dalla pulizia
(che su quella coppia vale circa 9 USD). Questa convenzione preesistente non è
stata modificata e merita un controllo economico separato nei benchmark.

## Verifiche

- 134 test MARIO passati, inclusi limiti, segni, unità/scala, conservazione del
  punto grezzo in caso di rifiuto, accettazione e rifiuto contabile e controllo
  stretto di X. I 124 test già presenti sono stati eseguiti con i nuovi test;
  dopo una correzione dell'audit sono stati rieseguiti i 10 test pertinenti.
- 4 test della pubblicazione della pipeline passati: incluse copie immutate,
  punti grezzo/ripulito e marcatura esplicita del risultato approssimato.
- I 24 CSV CVXLab della nuova prova a 13 regioni sono identici byte per byte
  a quelli della precedente prova con filtro dei prior.
- Per entrambe le prove, baseline sorgente, baseline di lavoro e workbook
  sorgente risultano immutati. Nessun nuovo preprocessing o riconciliazione.
- Per il risultato accettato, tutti i valori salvati nel database SQLite CVXLab
  coincidono esattamente con lo snapshot del punto ripulito. I Parquet finali
  sono stati riletti per controllare gli output e il numero di settori.

## File pubblicati

- CHR 13, input e diagnostica: [20261023 1238 - 13 regions and 1 sectors](</Users/lorenzorinaldi/Library/CloudStorage/OneDrive-SharedLibraries-WSPO365/RCD-Entice-EXT - Documents/General/2.Deliverables and Milestones/WP2. Improved data and empirics on trade and climate/Data split/Inventories/D2.8 inventories/20261023 1238 - 13 regions and 1 sectors>).
- CHR 13, database: [Parquet e checkpoint](</Users/lorenzorinaldi/Library/CloudStorage/OneDrive-SharedLibraries-WSPO365/RCD-Entice-EXT - Documents/General/2.Deliverables and Milestones/WP2. Improved data and empirics on trade and climate/Data split/Database/D2.8/20261023 1238 - 13 regions and 1 sectors>).
- CHR 49, input e diagnostica: [20261023 1239 - 49 regions and 1 sectors](</Users/lorenzorinaldi/Library/CloudStorage/OneDrive-SharedLibraries-WSPO365/RCD-Entice-EXT - Documents/General/2.Deliverables and Milestones/WP2. Improved data and empirics on trade and climate/Data split/Inventories/D2.8 inventories/20261023 1239 - 49 regions and 1 sectors>).

Gli allegati conservano configurazioni, sorgenti MARIO esattamente eseguiti,
workbook e baseline esatti, log, profilo RAM, audit dei prior e delle correzioni,
residui grezzi/ripuliti, analisi economica e checksum. I vecchi esperimenti non
sono stati sovrascritti. Il codice rimane sul branch locale `codex/mrio-memory`;
non è stato eseguito un push.

## Riproduzione

Selezionare i worktree `codex/mrio-memory` di MARIO, CVXLab e Database
disaggregation nel PYTHONPATH. Dalla root della pipeline:

```bash
python scripts/run_model_trial.py \
  --prepared build/memory-study/13/prepared \
  --output build/model_trials/new-empty-folder \
  --options config/model-trials/kl-prior-floor-cleanup.json \
  --solver MOSEK \
  --solver-options config/model-trials/memory-mosek.json \
  --stop-after-step 'Memory probe'
```

Per il caso a 49 regioni sostituire soltanto il percorso della preparazione e
usare una nuova cartella di output. I limiti della prova devono essere valutati
esplicitamente prima di cambiare il budget; la configurazione non li aumenta
automaticamente.
