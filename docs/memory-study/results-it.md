# MRIO: risultati delle prove di memoria e stima della RAM

21 ottobre 2026 — **nessun nuovo database KL accettato**. Sono state ridotte alcune rappresentazioni temporanee mantenendo il modello economico corrente. Rimangono due limiti distinti: la certificazione numerica della soluzione KL e il consumo di memoria alle dimensioni native.

Il caso reale introduce soltanto **CHR**, con 76 settori di partenza e 77 dopo l'inserimento. “67 settori” nelle prove precedenti indica 67 nuovi settori, cioè 143 settori totali. La geografia nativa effettiva ha 163 regioni.

## Risultato numerico e motivo dell'arresto delle prove di soluzione

Sono state eseguite due sole soluzioni reali: CHR a 13 regioni sul primo codice ottimizzato e un controllo sul codice precedente. Entrambe usano lo stesso workbook, la stessa baseline e le stesse opzioni KL/MOSEK. La preferenza per cross entropy è stata interpretata come l'attuale `Split_sectors_MRIO_KL`, l'ultima formulazione entropica concordata; il template storico `Split_sectors` non è stato ripristinato.

Gurobi completa la verifica affine preliminare. MOSEK dichiara `optimal` in circa **2,10 secondi** in entrambi i casi. La validazione successiva registra però:

- obiettivo CVXPY non finito;
- **33.988 celle di vincolo/dominio** oltre la precisione richiesta;
- scostamento massimo **0,02250617 M USD**, circa **22.506 USD**;
- stessi valori di controllo sul codice precedente e su quello ottimizzato.

Il rifiuto quindi comprende anche scostamenti nei vincoli: rendere finita la sola valutazione del log non basterebbe a certificare il risultato. La verifica affine non è una certificazione dell'accuratezza della successiva soluzione entropica. Questi esiti non dimostrano un'infeasibilità matematica.

I 24 CSV numerici consegnati a CVXLab sono **identici byte per byte** nei due casi. La successiva revisione del lettore mantiene gli stessi 24 CSV a 13 regioni e gli stessi 24 a 49 regioni. Non sono stati eseguiti altri tentativi di soluzione dopo il controllo sul codice precedente.

La regola di Camilla rimane applicata letteralmente: nel caso a 13 regioni il minimo non nullo è circa 8,9474e-16 M USD, il coefficiente è 1e-20 M USD e in unità scalate diventa 1e-23. Questa è evidenza di una scala numerica molto ampia, non la dimostrazione che quel coefficiente sia da solo la causa del problema. Cambiarlo richiederebbe una scelta metodologica esplicita; non è stato aumentato automaticamente.

Non sono stati applicati clipping, riconciliazioni aggiuntive, allentamenti dei vincoli, solver alternativi o obiettivi quadratici. Non essendoci un checkpoint accettato, non è stata costruita una dashboard di benchmark per un nuovo database.

## Consumi misurati

Mac con 18 GiB di memoria, Python dell'ambiente MARIO, CVXPY 1.9.2, CVXLab 1.1.0, MOSEK 11.2.6, Gurobi 13.0.2. Due thread per le librerie numeriche e per MOSEK. Le misure sono singole esecuzioni, con possibili effetti di cache e compressione: non sono medie di un benchmark ripetuto.

| Caso | Percorso ed esito | Tempo totale s | Footprint massimo GiB | RSS massimo GiB |
| --- | --- | ---: | ---: | ---: |
| 13, codice precedente | KL/MOSEK, rifiutato | 28.2 | 1.34 | 2.47 |
| 13, prima revisione memoria | KL/MOSEK, rifiutato | 24.0 | 1.25 | 1.78 |
| 49, prima revisione memoria | Solo preparazione, completata | 128.1 | 3.51 | 4.04 |
| 163, prima revisione memoria | Solo preparazione, arresto a 10 GiB | 142.4 | 10.00 | 6.10 |
| 13, lettore progressivo | Solo preparazione, completata | 14.9 | 0.33 | 0.59 |
| 49, lettore progressivo | Solo preparazione, completata | 99.9 | 1.43 | 2.79 |
| 163, lettore progressivo | Solo preparazione, arresto a 10 GiB | 144.9 | 10.36 | 5.56 |

Il tempo totale comprende avvio e chiusura del monitor; nei due tentativi di soluzione comprende anche la gestione degli esiti e l'eventuale pubblicazione. Le preparazioni di origine erano già disponibili: la loro creazione e riconciliazione non sono conteggiate.

**I profili di sola preparazione non includono solver, canonicalizzazione conica, ricostruzione o salvataggio dei risultati.** I due casi a 13 regioni con soluzione non sono confronti di fase omogenea con i profili senza solver. Il confronto a 49 regioni è invece sullo stesso percorso di preparazione e sugli stessi input.

Su macOS il monitor misura anche il footprint del processo e dei suoi figli tramite `proc_pid_rusage`. Include costi che RSS può non rappresentare correttamente quando intervengono compressione e swap. I due indicatori non sono intercambiabili. Il campionamento è ogni 0,5 secondi: un picco più breve potrebbe sfuggire e non si ottiene il massimo di tutte le altre applicazioni del computer.

Il limite è 10 GiB per footprint e RSS, con 8 GiB di disco libero e 2.400 secondi di durata massima. Gli arresti per risorse non sono fallimenti matematici. Il monitor interrompe soltanto il proprio gruppo di processi. I manifest dei processi terminati forzatamente vengono chiusi esternamente solo dopo averne verificato la fine e l'integrità degli input.

Il monitor interviene quando il campione supera la soglia: non impone un limite di allocazione al sistema operativo. Una crescita rapida tra due campioni può produrre un picco superiore a 10 GiB, come nella seconda prova nativa.

## Benefici verificati e loro limiti

La prima revisione, senza il lettore progressivo, riduce a 13 regioni il footprint da 1.34 a 1.25 GiB e RSS da 2.47 a 1.78 GiB. Il tempo MOSEK rimane praticamente identico. Il beneficio è nella gestione dei dati e delle strutture, non nella qualità o velocità dell'ottimizzazione.

Il primo profilo a 163 regioni supera il limite mentre il programma è ancora nel caricamento della preparazione, prima del log di ingresso nel motore add-sectors. L'ispezione del lettore identifica le due copie complete dell'Excel. Una sola revisione mirata introduce la lettura progressiva dei file senza formule, dopo test su valori, celle vuote, dimensioni errate e formule tra fogli.

A 49 regioni, questa revisione riduce il footprint della preparazione da **3.51 a 1.43 GiB**, circa **59.2%**, e il tempo da **128.1 a 99.9 secondi**, circa **22.0%**. I CSV rimangono identici. Il confronto misura l'effetto aggiuntivo del lettore: entrambe le esecuzioni usano già bridge e coordinate CVXLab ottimizzati.

La seconda e ultima misura nativa ha stato **resource_stopped**. L'ultima fase registrata è `motore add-sectors MARIO: filling IOT slices for CHR`. Le ultime righe del log e il profilo completo sono allegati alla diagnostica. Non è stato lanciato il solver nativo a 163 regioni e non è stato tentato un terzo esperimento.

Il bridge filtrato evita inoltre un costo analiticamente quantificabile: a 163 regioni e due nuovi settori dello stesso padre, le due Z avrebbero prodotto circa **315 milioni di righe** lunghe; ora ne servono circa **16,2 milioni**. Per un inserimento tardo di due figli dello stesso padre verso 143 settori totali, si passa da circa **1,072 miliardi a 30,0 milioni di righe**.

Nel secondo esempio, i soli array di sei colonne da otto byte passano da circa **47,9 a 1,34 GiB**. Sono dimensioni nominali delle tabelle Z del bridge: escludono indici, etichette, temporanei, altre tabelle, matrici dense e solver. Non significa che la RAM dell'intera pipeline sia ora 1,34 GiB. Queste dimensioni native sono calcoli di struttura, non allocazioni eseguite tutte in memoria durante lo studio.

## Dimensione del problema completo

Con 163 regioni, una sola Z densa della baseline occupa circa **1,14 GiB**. Con 143 settori totali, una Z float64 occupa circa **4,05 GiB**. La pipeline mantiene più matrici, riferimenti e temporanei: il costo totale supera quello di una sola Z.

| Settori totali dopo il passo | Nuovi settori nel passo | Padri coinvolti | Una Z densa GiB | Variabili scalari KL prima dei coni |
| ---: | ---: | ---: | ---: | ---: |
| 77 | 1 | 1 | 1.17 | 8.293.766 |
| 78 | 2 | 1 | 1.20 | 12.520.356 |
| 143 | 1 | 1 | 4.05 | 15.307.982 |
| 143 | 2 | 1 | 4.05 | 22.882.266 |
| 143 | 2 | 2 | 4.05 | 30.403.412 |
| 143 | 67 | 12 | 4.05 | 443.046.062 |

I conteggi includono le variabili positive/negative di V del template corrente, quattro fattori e quattro categorie di domanda finale. Sono verificati sui problemi costruiti a 13 e 49 regioni, rispettivamente 53.066 e 750.386 variabili. Per gli scenari nativi e finali sono conteggi analitici. Con R regioni, N settori totali e A settori padre/figli attivi, la formula è `R² A (2N − A) + 4R² A + 13RA`.

I coni entropici introducono altre variabili e strutture. Nel piccolo caso reale, 53.066 variabili del modello diventano 360.674 variabili scalari nella forma passata inizialmente a MOSEK. Quel moltiplicatore non è una legge universale per prevedere RAM o fattorizzazione. La struttura sparsa e il fill-in possono dominare il costo del solver.

## Stima prudente della RAM

Il dato misurato più utile per la preparazione completata è **1.43 GiB a 49 regioni e 77 settori totali**, senza solver. Una semplice proiezione quadratica nel numero di regioni dà **circa 16 GiB** per la stessa fase a 163 regioni. Proiettare anche la parte densa da 77 a 143 settori porta a **circa 55 GiB**. Sono riferimenti di scala, non stime validate del picco: confondono componenti fisse, dense e filtrate e non includono il solver.

Per pianificare risorse, manterrei questi ordini di grandezza:

- **64 GiB**: macchina su cui profilare il primo problema nativo con uno o due settori. Non è una garanzia che l'intera soluzione KL rientri o sia numericamente accettabile.
- **128–256 GiB, con possibilità di salire**: budget prudenziale per valutare il completamento nativo a passi di uno o due settori, fino a 143 totali. Non è un minimo misurato né una certificazione di sufficienza. Il picco dell'ultimo passo conta più della somma delle RAM dei singoli passi.
- **Tutti i 67 insieme**: circa 443 milioni di variabili prima dei coni. L'ordine di grandezza può diventare centinaia di GiB o TB; non è stato dimensionato né provato e non prenoterei una macchina contando su una stima puntuale. Anche il vantaggio del filtro diminuisce quando quasi tutti i blocchi sono attivi.

Le ottimizzazioni riducono molto alcuni costi evitabili; non consentono ancora di certificare una nuova RAM minima per il calcolo completo. Il Mac da 18 GiB non è una piattaforma sulla quale sia stata dimostrata la soluzione nativa. Il precedente arresto a circa 20 GiB con due settori resta soltanto un riferimento storico: usa codice, percorso e numero di settori diversi e non è un confronto controllato con questi profili.

## Dove rimane lavoro da fare

La priorità metodologica è ottenere un caso KL numericamente certificabile a piccola scala. Il rifiuto a 13 regioni era già presente prima delle modifiche di memoria e non può essere nascosto accettando lo stato del solver. Occorre riesaminare condizionamento, supporto entropico e accuratezza della soluzione con una decisione esplicita sulle ipotesi; non è stata presa automaticamente durante la notte.

Sul piano della memoria restano copie di database e matrici dense nel passaggio intermedio e nel motore MARIO, costanti che rispettano ancora il contratto NumPy di CVXLab, strutture SQL/parametri e canonicalizzazione CVXPY. La sola preparazione non misura i costi di Gurobi o MOSEK. Un caricamento selettivo degli inventari attivi, conservando tutti i budget futuri, sarebbe un ulteriore intervento da progettare in MARIO/pipeline: qui non è stato implementato. Non è stata estesa la modifica a CVXLab oltre i tre file concordati.

## Codice, riproducibilità e collocazione dei risultati

Tutti e tre i nuovi branch si chiamano **`codex/mrio-memory`** e rimangono locali, senza merge nei branch di lavoro precedenti e senza push. I commit di implementazione sono:

| Progetto | Base | Commit dello studio |
| --- | --- | --- |
| MARIO | `9863cda` | `6cbbef8`, poi `746e2ca` per il lettore |
| CVXLab | tag `v1.1.0`, `28b23ed` | `ae85624` |
| Database disaggregation | `4bda2e8` | `a8abba2`, `d1b6549` |

I worktree locali sono:

- `/Users/lorenzorinaldi/Documents/GitHub/MARIO/.worktrees/mrio-memory`
- `/Users/lorenzorinaldi/Documents/GitHub/cvxlab/.worktrees/mrio-memory`
- `/Users/lorenzorinaldi/Documents/GitHub/Database disaggregation/.worktrees/mrio-memory`

La diagnostica locale è in `build/memory-study/` del terzo worktree: JSON riassuntivo, campioni di memoria, log, hash, preparazioni e copie di lavoro. Per importare il codice giusto occorre includere esplicitamente i due worktree delle librerie e `src` della pipeline in `PYTHONPATH`; non è stato cambiato l'ambiente installato dell'utente.

I documenti e gli allegati condivisi sono nella cartella già pubblicata della prova rifiutata:

`/Users/lorenzorinaldi/Library/CloudStorage/OneDrive-SharedLibraries-WSPO365/RCD-Entice-EXT - Documents/General/2.Deliverables and Milestones/WP2. Improved data and empirics on trade and climate/Data split/Inventories/D2.8 inventories/20261021 2304 - 13 regions and 1 sectors`

Contiene soltanto input e diagnostica: **non esiste una nuova cartella database corrispondente**. Il sottopercorso `diagnostics/memory-study/` raccoglie i profili di tutto lo studio e l'archivio degli input esatti. I database già accettati nelle prove precedenti restano invariati. Gli `.md` sono anche sul Desktop e in `docs/memory-study/` della repository.

`exact-inputs.zip` conserva le tre preparazioni usate, incluse baseline, workbook e manifest. Gli input Excel condivisi possono ricevere metadati Office dal servizio di sincronizzazione: l'archivio conserva i byte locali realmente utilizzati. I report di integrità attestano che i workbook sorgente e le baseline delle prove non sono cambiati.

Nel rapporto delle modifiche sono descritti file e scelte. Il gruppo di 132 test mirati passa; la verifica legacy estesa mantiene gli stessi sei fallimenti osservati sul codice precedente. Nessun nuovo database è stato dichiarato valido e nessun benchmark economico nuovo viene presentato come risultato di questo studio.
