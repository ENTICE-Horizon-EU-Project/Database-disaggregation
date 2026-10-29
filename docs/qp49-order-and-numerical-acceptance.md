# Quadratica a 49 regioni: accettazione numerica e ordine dei settori

28 ottobre 2026. **Completati COB e MCU, uno alla volta, con quadratica e Gurobi.** Il database ha 49 regioni e 78 settori totali (76 iniziali più i due Mining). L'ordine completato è COB → MCU. Il punto finale era già `optimal`: è stato recuperato senza una nuova ottimizzazione e senza cambiare alcuna cella. E rimane da ricalcolare.

## Il blocco da circa 9 USD era nel validatore

Il secondo passo, MCU dopo COB, ha concluso regolarmente in Gurobi. Il vecchio validatore di MARIO ha poi bloccato l'esportazione perché otto celle non rispettavano la sua precisione di riferimento. Il residuo massimo era **8,968868 USD**, non un'infattibilità dichiarata dal solver. Era incoerente con la regola già concordata per KL: i residui monetari devono essere diagnostici e non comportare un rifiuto automatico di una soluzione `optimal`.

La soluzione salvata è stata recuperata dai vettori originali. Tutte le verifiche di corrispondenza fra variabili, coordinate e tabelle sono rimaste attive. La proiezione dei domini e degli zeri strutturali ha modificato **zero celle**. Anche l'obiettivo ricostruito coincide con quello originale, a precisione numerica. I vecchi manifest con il rifiuto del validatore sono conservati come cronologia, separati dal risultato accettato.

## Modifiche al codice standard

- **MARIO, `cvxlab_bridge.py` e `split_solution.py`:** per i modelli MRIO nominati, uno stato esattamente `optimal` attiva automaticamente la proiezione post-solver e la diagnostica monetaria senza soglie di rifiuto. Vale per KL, quadratica e formulazioni miste. La proiezione funziona anche quando la quadratica non ha le due variabili ausiliarie di V signed. Si conservano punto grezzo, punto esportato e audit completo delle correzioni. Non serve un nuovo argomento a `add_sectors`.
- **MARIO, `add_sector_steps.py`:** la stessa regola vale dopo la ricostruzione e ai checkpoint, per riaggregazione e contabilità monetaria, inclusi X e VY. I confronti continuano a riportare i propri valori e gli eventuali flag falsi. La politica numerica viene registrata separatamente dalle impostazioni matematiche del modello. Gli stati del solver diversi da `optimal` non vengono promossi; dati non finiti e coordinate incompatibili rimangono errori tecnici.
- **Database disaggregation:** nel runner delle prove, gli eccessi monetari dei budget del padre vengono scritti come diagnostica. Un piccolo residuo di un checkpoint non impedisce di costruire il passo successivo. Copertura incompleta, unità errate, duplicati, coordinate errate e dati non finiti restano controllati. La verifica stretta nella preparazione dei dati rimane disponibile separatamente.
- **CVXLab:** nessuna modifica. Non sono cambiati funzione obiettivo, equazioni, vincoli, solver, impostazioni Gurobi, scala, prior, baseline o target. Non è stata introdotta un'ottimizzazione di riparazione.

La precisione di riferimento resta utile per evidenziare gli scarti; non è una soglia economica di validità. Il risultato esportato conserva lo stato `optimal` del solver e la revisione economica pendente. Se in un'altra prova la proiezione cambierà delle celle, l'audit lo mostrerà: non verrà attribuita al punto modificato una nuova certificazione di ottimalità.

La ripresa confronta esattamente i sorgenti matematici, distinguendoli dal modulo di post-elaborazione `split_solution.py`. Cambiare soltanto questo modulo non obbliga a ripetere la soluzione: il suo hash completo rimane registrato e il cambio viene annotato separatamente. Gli hash di workbook, operatori e costruzione del modello devono continuare a coincidere. La verifica sui checkpoint pubblicati ha confermato questa compatibilità. I modelli storici selezionati con `split_model_options=None` mantengono il percorso storico; le prove correnti usano i modelli MRIO nominati.

## Risultati e risorse

| Passo | Stato nativo | Intera esecuzione locale | Picco footprint fisico |
|---|---|---:|---:|
| COB dalla baseline originale | optimal | 357,76 s | 6,12 GiB |
| MCU dopo COB | optimal | 265,03 s | 6,23 GiB |
| Recupero del punto finale, senza solver | nessuna nuova ottimizzazione | 83,60 s | 1,66 GiB |

I tempi comprendono preparazione e controlli; la pubblicazione è esclusa. L'ottimizzazione nativa di MCU dura circa 4,90 secondi. Le due righe di soluzione sono processi separati, uno per settore: i picchi di memoria non vanno sommati. Queste misure non dimostrano ancora che tutti i 67 nuovi settori possano essere completati sul Mac.

Il massimo scarto di Z riaggregata rispetto al checkpoint COB è **8,167380 USD**. Il controllo dei 65 settori pendenti trova un solo eccesso commerciale di riferimento, OXT Brasile → Bulgaria, pari a **3,593251 USD**. Entrambi rimangono diagnostici e non invalidano il risultato. Gli output e i target originali sono conservati; nessun target è stato riconciliato fra i passi. La riconciliazione iniziale comune alle prove rimane quella documentata in `qp49-protected-steps.md`, con le sue variazioni sostanziali di trade esplicitate nell'audit.

L'altro ordine, MCU → COB, rimane invece incompleto: Gurobi termina il secondo passo per difficoltà numeriche, prima di restituire un punto `optimal`. Cambiare la politica del validatore non trasforma quel fallimento nativo in una soluzione.

## L'ordine può cambiare anche il risultato economico

Sì: ogni passo conserva come vincoli i risultati aggregati dei passi precedenti. Se il padre dispone di 100 di elettricità e il primo figlio ne assorbe 80, il secondo può utilizzare soltanto i 20 rimasti. Invertendo i figli, la prima decisione può essere diversa. I prior sui fornitori futuri permettono affinamenti successivi, ma conservano il totale precedentemente assegnato; non riaprono tutte le decisioni precedenti su altri input, V e Y. Questo vale sia per KL sia per la quadratica.

Per misurare un primo effetto, abbiamo riaggregato COB nel padre OXT nel risultato COB → MCU e confrontato MCU alla stessa classificazione del checkpoint MCU-first. **Non è un confronto fra due database finali completi**, perché MCU → COB non è stato completato. Misura le differenze nelle decisioni su MCU che il primo passo del percorso opposto ha già fissato.

| Flussi di MCU | Somma assoluta delle differenze | In percentuale del totale assoluto di riferimento |
|---|---:|---:|
| Input intermedi | 1.718,95 milioni USD | 2,5591% |
| Vendite intermedie | 833,26 milioni USD | 0,7312% |
| Domanda finale | 14,29 milioni USD | 0,5919% |
| Valore aggiunto | 473,27 milioni USD | 0,9613% |

Sono distanze L1, cioè somme di differenze assolute; non aumenti netti dei totali. L'output di MCU coincide a precisione di macchina e la massima differenza sui trade regionali di MCU è circa 0,85 USD. Le differenze nella composizione degli input sono quindi economicamente separate dai residui di pochi dollari. Il dato globale sugli input è significativo, ma non prova che ogni settore o regione cambi drasticamente. L'audit JSON conserva anche le distanze regionali e i casi a output nullo.

La presenza di piccoli valori positivi dopo il primo passo può contribuire al condizionamento numerico. Per COB dopo MCU i prior Zold contengono 47.648 valori positivi inferiori a 1 USD, contro zero nella baseline originale. Tuttavia MCU dopo COB risolve pur avendone 18.154: non abbiamo dimostrato che questi valori siano la causa unica del fallimento. Non sono stati eliminati valori dal checkpoint per far risolvere il modello.

## Dove sono i file

Nel Data split di WSP:

- `Database/D2.8/20261028 1221 - 49 regions and 1 sectors`: COB-first, 77 settori totali.
- `Database/D2.8/20261028 1230 - 49 regions and 2 sectors`: COB e MCU, 78 settori totali, risultato finale della prova.
- `Inventories/D2.8 inventories/`: cartelle con gli stessi identici nomi e timestamp, con input cumulativi, piano, ultimo passo e settori rimanenti.

Nelle rispettive cartelle `diagnostics` sono conservati log e risorse native, budget futuri, punto originale e punto esportato, recupero, confronto degli ordini e riconciliazione iniziale. `exact_trial_inputs.zip` conserva i byte degli input della prova con checksum verificati. Non eseguire i 65 rimanenti come un unico gruppo: `Remaining sectors` è un piano da suddividere prima di proseguire.

Il workspace locale è `build/model_trials/20261028_qp49_order_diagnostic_01`. Le ottimizzazioni già concluse non sono state ripetute dopo il recupero. Le modifiche restano nei branch locali `codex/mrio-memory`; questa attività non esegue commit, push o pubblicazione di documentazione aperta.

## Verifiche

I test di regressione controllano esportazione automatica della quadratica con residui monetari, proiezione dei soli domini vietati, conservazione dei negativi legittimi, assenza di un tetto alle correzioni, stati solver distinti, errori tecnici e checkpoint. Si verificano anche i budget diagnostici nella pipeline e la pubblicazione dei risultati. I risultati delle verifiche e i limiti della build della documentazione sono registrati nel riepilogo del workspace. Gli esempi di documentazione sono stati ispezionati; non sono state eseguite nuove prove globali.

Verifica conclusa: **176 test distinti superati** fra MARIO e pipeline. Il successivo controllo mirato della compatibilità e dei passaggi KL/partial ha superato 29 test (in parte già inclusi nei 176). Ricaricati entrambi i database pubblicati e verificati checksum, classificazioni e identità fra punto finale grezzo ed esportato. La build completa locale della documentazione ha segnalato due link a ZIP mancanti in un notebook non modificato; la build incrementale delle pagine aggiornate è conclusa senza avvisi. Nessun sito è stato pubblicato.
