# Modifiche alla memoria della pipeline MRIO

Studio del 21 ottobre 2026. Riferimento: stato dei tre progetti prima dei nuovi branch locali `codex/mrio-memory`. Questo documento descrive soltanto le modifiche dello studio sulla memoria; le precedenti revisioni economiche e di armonizzazione non vengono attribuite a questo lavoro.

La pipeline rimane MARIO → CVXLab → CVXPY → solver. L'obiettivo delle modifiche è evitare rappresentazioni e copie inutili delle stesse matrici. Non è stata implementata la procedura SRIO di Maksym.

## Ambito e limiti concordati

- Un solo settore per le prove effettivamente eseguite: CHR. Nessuna catena di gruppi o completamento dei 67 settori.
- KL come formulazione entropica di riferimento e MOSEK per la soluzione. Gurobi esegue soltanto la verifica affine preliminare.
- Nessun passaggio automatico alla funzione quadratica, nessun cambiamento di solver per cercare un risultato accettabile.
- Dati, prior, output, trade, domini di V/Y, pesi e tolleranze economiche conservati.
- Limite di 10 GiB sia per il footprint macOS sia per RSS, riserva disco di 8 GiB, durata massima di 2.400 secondi; MOSEK limitato a 600 secondi e due thread.
- Nessun risultato viene considerato valido soltanto perché il solver dichiara `optimal`.

La scelta di CHR evita il problema già noto dei prior attivi negativi di Capital/Labor per MCU in Brasile. Non corregge quel problema: lo tiene fuori da questo esperimento. La preparazione nativa di CHR contiene anche un prior negativo di Capital in Giappone, ma con output preparato pari a zero. Non è stato modificato.

## MARIO: cambiamenti principali

### 1. Riutilizzo dei riferimenti già disponibili nel motore add_sectors

Prima, il chiamante conservava le matrici originali per costruire il problema di split e il motore ne raccoglieva nuovamente una copia. Ora il motore può ricevere i riferimenti difensivi già raccolti. Crea oggetti DataFrame separati con gli stessi buffer numerici: questo isola le modifiche ai nomi degli assi senza duplicare i dati.

Inoltre, le slice appena allocate vengono riempite direttamente. Le matrici di incertezza inizializzate a uno vengono allocate direttamente a uno, evitando il precedente percorso `deepcopy(z) * 0 + 1` e i suoi temporanei.

File: `mario/api/database.py`, `mario/ops/add_sector_engine.py`. Il nuovo parametro è interno al motore; non è una nuova opzione economica di `add_sectors`.

### 2. Trasferimento a CVXLab dei soli blocchi che entrano nel problema

Prima, il bridge trasformava tutta Z originale e tutta Z della preparazione in lunghe tabelle con etichette, anche per le coppie di settori non interessate dallo split. Il costo cresceva con il quadrato del numero complessivo di settori e regioni.

Ora vengono appiattiti:

- Z: righe dei settori padre/figli verso tutte le colonne, più righe degli altri settori verso colonne padre/figli;
- Y: soltanto le righe padre/figli;
- V: soltanto le colonne padre/figli;
- X: il vettore degli output.

L'unione evita di contare due volte il blocco padre/figli × padre/figli. Non elimina flussi economici: le celle non ottimizzate restano nelle matrici originali, conservate per riferimento. Le tabelle lunghe vengono liberate prima di entrare nella soluzione.

File: `mario/ops/cvxlab_bridge.py`.

### 3. Ricostruzione delle matrici a partire dai blocchi

Prima, il ritorno da CVXLab combinava tabelle lunghe e ne ricostruiva le matrici con operazioni di pivot. Ora viene allocata una matrice finale, copiata la parte originale in blocchi di 256 righe e assegnate direttamente le celle ottimizzate.

Coordinate e ordinamento vengono conservati secondo il comportamento precedente. I test includono V e Y con segno negativo, zeri strutturali e assi deliberatamente non ordinati. La via precedente rimane disponibile per i chiamanti interni che passano normali dizionari di tabelle.

File: `mario/ops/cvxlab_bridge.py`.

### 4. Un operatore già sparso rimane sparso

`block_diag` costruiva una matrice sparsa e subito la convertiva in una matrice densa prima di passarla a CVXPY. Ora passa direttamente la costante sparsa. La matrice e l'algebra sono identiche.

File: `mario/ops/cvxlab_models/Split_sectors/user_defined_operators.py`. Gli operatori dei template MRIO lo riutilizzano. Nessuna riga di obiettivo o vincolo nei file `model_settings.xlsx` è stata modificata.

È stata valutata anche la possibilità di restituire direttamente identità sparse dai generatori di costanti. I test hanno mostrato che il contratto attuale di CVXLab richiede array NumPy e applica già una propria conversione. Quel tentativo è stato annullato: non fa parte del codice finale e non è stato ampliato CVXLab per supportarlo.

### 5. Lettura progressiva degli Excel senza formule

Il primo profilo nativo ha evidenziato un costo precedente al motore: il lettore apriva in memoria due copie complete del workbook, una con formule e una con valori calcolati. Il file nativo ha 10.921 inventari più dieci schede di supporto, anche quando viene selezionato un solo settore.

Ora il lettore percorre le schede in modalità progressiva. Se non trova formule, costruisce direttamente gli stessi DataFrame e chiude il workbook. Se incontra una formula, chiude la lettura progressiva e usa il lettore precedente, conservando valori cached, riferimenti tra fogli ed eventuale valutazione delle formule. Le righe vengono completate con celle vuote come nel lettore precedente; le dimensioni dichiarate dal produttore vengono ricalcolate per non perdere celle.

File: `mario/ops/add_sector_workbook.py`. Non cambia il formato degli inventari, non carica soltanto il settore attivo e non elimina il controllo degli altri 66 settori. I dati di tutte le schede sono ancora letti; si evita la permanenza in memoria degli alberi di celle di openpyxl quando non servono. Il beneficio non è garantito per workbook contenenti formule, che usano il percorso storico.

## CVXLab: intervento limitato a tre file

Il problema era una duplicazione nella generazione delle coordinate: CVXLab costruiva l'intero prodotto cartesiano della tabella e poi eliminava le coordinate non usate da alcuna variabile. In un MRIO, il prodotto completo può essere molto più grande del problema effettivo.

Ora una funzione comune costruisce i prodotti cartesiani delle sole coordinate dichiarate dalle variabili, ne prende l'unione e ripristina l'ordine della tabella originale. Controlla prima che tutte le coordinate siano ammesse. Sostituisce anche un successivo confronto che duplicava grandi tabelle.

File modificati:

- `cvxlab/support/util.py`: funzione comune di generazione filtrata;
- `cvxlab/backend/database.py`: uso nella creazione delle tabelle SQL;
- `cvxlab/backend/core.py`: uso per le variabili dei problemi senza coordinate di separazione inter-problema, come questo MRIO.

Il ramo con separazione inter-problema conserva il comportamento precedente. Non sono state modificate la formulazione dei problemi, le API dei solver, le regole di soluzione, la canonicalizzazione CVXPY o i file di configurazione dei modelli.

## Database disaggregation: orchestrazione e misure

La policy non clona più il database prima di ogni tentativo, perché MARIO crea già il proprio candidato transazionale e lo conferma soltanto dopo i controlli. Riutilizza inoltre il workbook già caricato. L'ordine ordinario dei fallback della policy rimane invariato; queste prove lo escludono esplicitamente mediante un file di opzioni con un unico modello KL.

File: `src/database_disaggregation/core/model_policy.py`.

Questo risparmio riguarda l'esecuzione tramite policy. I profili KL a modello fisso di questo studio la bypassano: i loro miglioramenti misurati non vanno attribuiti alla rimozione di quel clone.

Sono stati aggiunti strumenti diagnostici:

- `prepare_memory_probe.py`: copia una preparazione esistente e modifica soltanto il foglio con il piano, selezionando uno o due settori. Verifica che ogni altro elemento ZIP del workbook sia identico. Tutti i settori futuri rimangono disponibili per i controlli dei budget e dei riferimenti.
- `profile_model_command.py`: avvia un processo isolato, ne misura memoria e durata e arresta soltanto il proprio gruppo di processi se supera i limiti. Su macOS misura anche `ri_phys_footprint`, perché RSS può sottostimare il costo in presenza di compressione/swap. Il monitor deve poter interrogare i processi; se non riesce, si arresta senza proseguire alla cieca.
- `profile_split_preparation.py`: osservatore diagnostico che percorre l'ordinaria chiamata `add_sectors` fino alla creazione dei problemi numerici CVXLab, poi si interrompe prima di qualsiasi solver. La sostituzione del confine di chiamata avviene solo nel processo diagnostico. Non è una nuova modalità produttiva e non genera database accettati.
- `memory-kl.json`, `memory-mosek.json`: configurazioni fisse e riproducibili delle prove.

I profili di sola preparazione escludono canonicalizzazione conica, verifica Gurobi, ottimizzazione MOSEK, ricostruzione finale e salvataggio del database. I loro picchi non sono stime della memoria totale di una soluzione.

L'osservatore termina attraverso un'eccezione intenzionale, quindi MARIO può scrivere `failure.json` nella directory temporanea del passo. Per questi profili lo stato da leggere è `prepared_only` in `preparation_profile.json`, insieme a `solver_called=false`; non si tratta di un fallimento del solver né di un checkpoint accettato.

## Che cosa non è cambiato nei dati e nel modello

Non è stata aggiunta nessuna riconciliazione di V, nessun prior basato sul padre, nessun bilanciamento SRIO o nuovo vincolo economico. Le fonti non sono state riscritte. Le prove usano le preparazioni già disponibili, con le scelte di armonizzazione che contenevano: “nessun cambiamento” significa rispetto a quelle preparazioni, non rispetto ai dati grezzi dei partner.

Rimangono la conservazione dei totali dei padri, i target di output/trade, l'accounting `inherit`, i domini di V/Y, la gestione dei segni e la regola di supporto entropico concordata con Camilla. E resta differita, come richiesto.

La funzione KL e i pesi di Y e supply sono quelli della configurazione corrente: 0,1 e 1. La scala è 1.000 e il controllo di obiettivo finito rimane obbligatorio. Nessun clipping delle soluzioni e nessun allentamento dei controlli è stato introdotto per ottenere un checkpoint.

## Validazione

- 132 test MARIO mirati passati, inclusi modelli, template, split delle matrici, passaggi intermedi, ripresa dei checkpoint e il nuovo lettore.
- 30 test CVXLab passati, inclusi cinque nuovi test di equivalenza delle coordinate.
- 19 test della pipeline passati su policy e budget dei settori padre.
- Monitor provato sia con un comando completato sia con un processo deliberatamente sopra il limite, arrestato correttamente.
- Confronto reale CHR a 13 regioni contro il codice precedente: tutti i 24 CSV numerici risultano identici byte per byte. Anche il controllo successivo a MOSEK dà lo stesso esito e gli stessi scostamenti. Questo dimostra l'equivalenza degli input del caso provato; non equivale alla validazione economica di un nuovo database.

La verifica è stata estesa anche al vecchio file di test `test_addsector.py`: nel gruppo complessivo risultano 189 test passati e sei fallimenti. Gli stessi sei fallimenti sono stati riprodotti dal checkout precedente `9863cda`, con il suo file di test e il CVXLab installato: 57 passati e sei falliti. Riguardano aspettative legacy sui metadati di split, output XLSX invece dei CSV correnti, una fixture Exclusions con vecchie colonne e un confronto binario di template riscritti dalla compatibilità runtime. Non sono stati corretti in questo studio. La suite estesa quindi **non è interamente verde**, anche se il gruppo mirato di 132 test passa.

I dettagli dei tempi, dei consumi, dei limiti numerici e delle stime per 163 regioni sono nel rapporto dei risultati.
