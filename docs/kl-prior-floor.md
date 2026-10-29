# Prova KL/MOSEK con filtro dei prior e riferimento massimo

23 ottobre 2026 — CHR (estrazione di cromo), 13 regioni, 76 settori iniziali e 77 dopo l'inserimento previsto.

**Esito: prova rifiutata; nessun nuovo database accettato.** È stata eseguita una sola prova MRIO, senza fallback a quadratica o ad altri solver. Gurobi esegue soltanto la verifica affine preliminare; la minimizzazione KL usa MOSEK. Non sono state eseguite ulteriori prove o modifiche automatiche di eps/tolleranze.

## Modifiche applicate

La configurazione `config/model-trials/kl-prior-floor.json` mantiene modello, pesi, accounting ereditato, scala, solver e tolleranze precedenti; aggiunge soltanto `prior_zero_tolerance=1e-6` nelle unità monetarie originali, qui M USD.

1. Nei soli prior dell'obiettivo, i moduli strettamente inferiori a `1e-6 M USD` (1 USD) sono azzerati prima della generazione dei file CVXLab e prima della divisione per la scala.
2. Il riferimento entropico è `max(q0, eps)`, con `eps=tol*1e-2=1e-8 M USD` (0,01 USD), anziché `q0+eps`. Dividendo per la scala 1000, eps diventa circa `1e-11`.
3. Z usa i riferimenti non negativi con pavimento. Y conserva il segno originale anche per un piccolo prior negativo azzerato: il modulo riceve il pavimento e il segno resta separato dalla magnitudine. I riferimenti scritti in CSV sono quindi i riferimenti dopo il pavimento, non semplicemente i valori dopo l'azzeramento. L'audit conserva entrambe le fasi.
4. V0 resta un prior netto con segno: nessun `max(V0,eps)` sulla V netta. Capital/Labor ricevono riferimenti non negativi; per Tax/TTM il pavimento è applicato separatamente alle componenti positiva e negativa. Due prior V negativi di modulo inferiore a 1 USD sono azzerati; gli altri cinque negativi sono preservati esattamente.
5. Gli zeri strutturali, i domini e i vincoli restano invariati. Un prior azzerato non diventa una nuova variabile obbligata a zero. Il supporto entropico non è un limite inferiore al flusso finale.

L'eps entropico è distinto dall'eps del foglio delle tolleranze contabili, che rimane invariato. I coefficienti tecnici degli inventari e i file sorgente non sono stati filtrati o riscritti. Le modifiche sono nel bridge e negli operatori MARIO, sul branch locale `codex/mrio-memory`. **Il codice CVXLab è invariato**, anche rispetto ai sorgenti caricati nella prova precedente.

## Audit dei prior

| Prior effettivo dell'obiettivo | Valori non nulli sotto 1 USD azzerati | Riferimenti portati al pavimento |
| --- | ---: | ---: |
| Z_use0 | 2426 | 9436 |
| Z_supply0 | 837 | 7012 |
| Y0 | 37 | 592 |
| V0 | 2 | nelle componenti dell’obiettivo |

Il vecchio riferimento di circa `8,95e-16 M USD` è stato rimosso correttamente dal prior Z_use0. I conteggi dei riferimenti includono anche celle già nulle; le maschere strutturali continuano a escludere dall'obiettivo quelle vietate, senza creare nuovi coni per esse.

`prior_preparation.csv` registra coordinate, valore originale, valore dopo soglia e riferimento scritto per ogni cella cambiata. `prior_preparation.json` ed `entropy_support.json` ne riassumono la regola e gli effetti.

## Confronto con il precedente CHR13

| Controllo | Precedente | Filtro + max |
| --- | ---: | ---: |
| Stato dichiarato da MOSEK | optimal | optimal |
| Obiettivo rivalutato finito | No | No |
| Celle di vincolo/dominio oltre tolleranza | 33,988 | 27,801 |
| Residuo assoluto massimo, USD | 22,506.17 | 8,660.85 |
| Tempo solver nativo, secondi | 2.10 | 3.25 |

Il residuo massimo è inferiore di circa 61.5%, ma la soluzione rimane fuori dai criteri di accettazione. I conteggi comprendono controlli ripetuti sullo stesso valore: non rappresentano necessariamente flussi economici distinti. Il residuo massimo è un indicatore assoluto; la violazione di ciascuna cella è valutata con la tolleranza assoluta e relativa già prevista, senza allentarla.

La verifica affine Gurobi trova un candidato entro il proprio inviluppo numerico. Questo non certifica il punto successivamente restituito dalla minimizzazione entropica. I valori di `max_violation` sono rivalutati nel modello originale.

Il solver impiega 3.25 secondi, la prova completa circa 18.4 secondi. Il monitor registra circa 0.85 GiB di footprint, sotto il limite di 10 GiB. Questi sono dati di una singola esecuzione rifiutata. La lettura progressiva non era presente nella precedente soluzione reale: i tempi totali e la memoria non sono un confronto isolato dell'effetto del filtro. Il problema non è stato fermato per RAM.

## Causa immediata dell'obiettivo infinito, ora identificata

Gli argomenti dell'entropia restituiti dal solver contengono valori negativi, anche se i rispettivi domini li vietano:

| Blocco dell'obiettivo | Operandi negativi | Negativo massimo in modulo, USD |
| --- | ---: | ---: |
| Z_use | 3,370 | 456.72 |
| Z_supply | 2,380 | 120.67 |
| Y | 137 | 10.71 |
| V | 2 | 7.26 |

Le due celle V sono Capital e Labor di CHR in “Rest of the World”, restituiti rispettivamente a circa −7,24 e −7,26 USD. Sono quantità che devono essere non negative, non Tax/TTM legittimamente negativi. Le due componenti non negative di Tax/TTM non hanno operandi negativi nell'entropia in questa prova.

La diagnostica separa ora vincoli espliciti e domini dell'obiettivo. Tra i residui maggiori ci sono uguaglianze dei bilanci di riga e colonna. Quindi un semplice trattamento della valutazione del log non certificherebbe il risultato. Nessun valore del punto restituito è stato corretto o tagliato a zero.

Questa identifica una causa immediata dell'infinito, non la causa ultima dell'accuratezza insufficiente del punto. Rimangono da esaminare il condizionamento e la restituzione del punto primale dalla soluzione conica/duale. Non è dimostrato che il problema economico sia infeasible.

## Integrità e verifica

- Identici alla prova precedente: workbook sorgente, baseline, opzioni MOSEK e tutti i sorgenti Python CVXLab.
- Identici byte per byte **19 CSV su 24**, inclusi Zold/Yold/Vold, output X, Trade, selettori, maschere e residui contabili. Cambiano esclusivamente Z_use0, Z_supply0, Y0, V0 e il coefficiente entropico in Model_controls; gli altri controlli numerici sono identici.
- Baseline sorgente e copia di lavoro hash-verificate invariate. I target e la preparazione non sono riconciliati di nuovo.
- **124 test mirati passati**: 100 su prior, obiettivi, template, diagnostica e memoria; 24 sull'inserimento a passi. I piccoli esempi dei test non sono ulteriori tentativi MRIO CHR13.
- Nessun nuovo database o dashboard economica è stato pubblicato per questa prova rifiutata. Gli input e la diagnostica sono nella cartella della prova, sotto `Inventories/D2.8 inventories`.

## Allegati

La sottocartella `diagnostics/kl-prior-floor/` contiene confronto JSON, audit di integrità, audit dei prior, operandi negativi con coordinate, residui per blocco, log e profilo risorse, punto grezzo restituito, configurazioni e patch dei sorgenti MARIO. Il punto grezzo è diagnostico e non è un database accettato. L'archivio degli input esatti conserva workbook sorgente e baseline, workbook compilato del passo e input CVXLab realmente utilizzati.

Per riprodurre, selezionare esplicitamente i worktree locali `codex/mrio-memory` in PYTHONPATH, ripristinare la preparazione esatta e usare:

```bash
python scripts/run_model_trial.py \
  --prepared /path/to/exact/prepared \
  --output /path/to/new/empty/trial \
  --options config/model-trials/kl-prior-floor.json \
  --solver MOSEK \
  --solver-options config/model-trials/memory-mosek.json \
  --stop-after-step 'Memory probe'
```

Il rapporto registra un singolo esperimento; non certifica una nuova configurazione standard o la soluzione KL a scala maggiore.
