# Responsabilità per la sequenza di disaggregazione dei settori

La gestione dei fallimenti è ora implementata nel worktree MARIO `codex/mrio-memory`, tramite `Database.add_sectors(..., on_step_failure="raise" | "continue")`. Anche il raccordo geografico è disponibile: vedere [GTAP model regions](gtap-model-regions.md).

## MARIO: comportamento generale dell'operazione

MARIO deve possedere l'intera sequenza di `add_sectors` con intermediate steps: tentativo di uno step su una copia, commit del risultato riuscito, conservazione dell'ultimo checkpoint dopo un fallimento e avanzamento allo step successivo. L'argomento `on_step_failure="raise"` mantiene l'interruzione predefinita; `"continue"` conserva il database precedente e passa al gruppo successivo dopo un fallimento di ottimizzazione riconosciuto. Ogni gruppo è atomico ed è tentato una sola volta per chiamata. Non vengono introdotti ritentativi automatici o cambi di solver, obiettivo o dati.

Appartengono a MARIO anche la distinzione fra settori completati, pendenti e rinviati; il giornale di ogni tentativo, anche se l'ultimo fallisce; il ripristino da checkpoint; e la ripresa dei rinviati mediante una nuova chiamata dal checkpoint. Se il parent di un gruppo è fallito, quel gruppo è registrato come blocked e non avvia il solver. I fallimenti di ottimizzazione previsti possono essere rinviati. Errori globali di integrità, incompatibilità dello stato e bug non devono essere trasformati silenziosamente in settori esclusi. Un punto restituito optimal segue la politica di esportazione e diagnostica monetaria già concordata.

Anche la proiezione degli input al parent è una responsabilità MARIO. Il workbook originale conserva la classificazione desiderata. A ogni step, i codici dei settori assenti, futuri o rinviati vengono ricondotti al più vicino parent presente; le osservazioni coincidenti vengono aggregate correttamente e le osservazioni sovrapposte vengono controllate. Se il figlio viene aggiunto più tardi, gli inventari originali supportano l'affinamento dei prior degli acquirenti già presenti. MARIO contiene già `compile_step` e `refinement_priors`: questa logica deve essere riusata e verificata sui salti, non duplicata nella pipeline.

Dato il piano ricevuto, anche la gestione dei budget residui fra gli step e la loro diagnostica appartengono a MARIO. La riconciliazione dei dati raccolti e la scelta delle ipotesi di preparazione rimangono nella pipeline.

La meccanica non contiene nomi o ipotesi ENTICE. La formulazione e i solver rimangono quelli esplicitamente selezionati. La scelta di proseguire dopo il fallimento non comporta un cambio automatico dell'obiettivo o dei dati.

## Database disaggregation: dati e impostazioni del progetto

La repository fornisce gli inventari, i codici dei figli e dei parent, le mappature tra classificazioni, i raccordi geografici e i dati output/trade. Decide inoltre la selezione e l'ordine dei settori della prova, la modalità di gestione dei fallimenti da richiedere a MARIO, il numero massimo di giri, la formulazione e i solver.

La preparazione e riconciliazione dei target e dei budget output/trade rimane qui, con audit delle ipotesi. I settori falliti rimangono economicamente nel parent; non si riassegnano automaticamente i loro target agli altri figli. La pubblicazione su WSP e i benchmark devono utilizzare il numero dei settori effettivamente completati e rendere visibile la copertura ancora aggregata nei residui.

La definizione economica `MCU -> OXT` viene dagli inventari e dalle corrispondenze del progetto. L'esecuzione della regola generica «se MCU è assente, usa OXT» appartiene a MARIO. Analogamente, il file che definisce le regioni ENTICE rimane qui; l'operazione generica di aggregazione di un database appartiene a MARIO.

La pipeline avvia e monitora l'esecuzione, ma non deve contenere una seconda implementazione concorrente della sequenza e del rollback.

## CVXLab

Nessuna modifica per questo comportamento: CVXLab continua a costruire e risolvere il singolo problema ricevuto da MARIO. I test eseguiti dimostrano fallimento del primo settore e successo del successivo, conservazione esatta dello stato al fallimento, proiezione verso il parent, ripresa e un numero finito di tentativi. Per questa modifica non è necessario cambiare la funzione obiettivo.

## Uso e verifiche

La pipeline prepara geografia, inventari e target **prima** di chiamare `.add_sectors`. Questi input restano invariati durante la sequenza. MARIO compila ogni step sulla classificazione effettivamente raggiunta: una modifica di questa vista operativa non è una nuova armonizzazione dei dati sorgente. Un fallimento non richiede di rilanciare il pre-processing.

```python
db.add_sectors(
    "add_sectors.xlsx",
    split=True,
    intermediate_steps=True,
    save_intermediates="run/checkpoints",
    on_step_failure="continue",
    solver=solver,
    split_model_options=model_options,
)
```

`run_report.json` contiene tutti i tentativi, anche quelli successivi all'ultimo checkpoint accettato. Ogni chiamata conserva inoltre un report proprio. I settori falliti rimangono nel parent e nel workbook rimanente. Se tutti i tentativi falliscono, i valori del database di partenza restano invariati e il report è partial. `stop_after_step` delimita i tentativi anche se il gruppo indicato fallisce.

La verifica mirata, comprendente i nuovi test e le regressioni della sequenza e del riferimento API, dà **44 passed**. Sono inclusi successi reali su piccole tabelle con Gurobi, fallimenti controllati e ripresa di un fornitore precedentemente saltato. L'inventario sorgente conserva il proprio hash. CVXLab e le formulazioni non sono stati modificati per questa funzione; non è stato eseguito un nuovo modello ENTICE di grandi dimensioni.

Le pagine guida e API sono state generate con Sphinx. La build completa segnala due riferimenti a ZIP mancanti nel notebook preesistente `from_txt`, esterni alla modifica. Le pagine interessate contengono il nuovo argomento e il collegamento reciproco guida/API.

Il runner `run_model_trial.py` ora espone `--on-step-failure {raise,continue}`. Il valore predefinito rimane `raise`. Per la singola passata con salti si specificano `--options`, `--solver` e `--on-step-failure continue`: il runner inoltra la scelta a MARIO e registra il report completo. La policy di fallback e la continuazione non sono combinate automaticamente; la CLI rifiuta questa combinazione per evitare due controllori concorrenti. La preparazione completa e la prima esecuzione a 61 regioni sono descritte nel rapporto interno `full61-sector-skip-run.md`, generato alla conclusione della prova.
