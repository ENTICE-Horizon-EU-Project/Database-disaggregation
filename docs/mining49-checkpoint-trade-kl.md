# Mining a 49 regioni: riconciliazione sul checkpoint CHR e prova KL/MOSEK

23 ottobre 2026. **Esito: MCU non completato; CHR resta l'unico nuovo settore accettato.** La sequenza si è fermata dopo un solo tentativo MRIO, senza fallback o modifiche a MARIO/CVXLab. Il checkpoint di partenza, la baseline e gli output sono rimasti invariati.

## I dati erano già stati puliti?

Sì. Il manifest della preparazione iniziale a 49 regioni documenta la riconciliazione congiunta di **tutti i 67 settori**, con zero violazioni finali di output, trade, esportazioni del produttore e copertura degli output. Il successivo conflitto è emerso rispetto alla baseline residua dopo l'inserimento di CHR: alcune rotte CHR erano prive di un target attivo, e CHR ha potuto assorbire trade necessario ai settori successivi.

La pulizia di unità, identità e segni ammissibili serve indipendentemente dall'aggregazione. La riconciliazione quantitativa dipende invece dai budget e dalla geografia: quando cambia l'aggregazione cambiano capacità e rotte estere. Questa specifica riconciliazione è condizionata soprattutto al checkpoint scelto, non soltanto al passaggio a 49 regioni. Non dimostra che la pulizia iniziale fosse stata dimenticata. La gestione sequenziale dovrebbe idealmente mantenere compatibilità con i target futuri, senza richiedere continue revisioni dei dati.

## Scelta autorizzata

È stato mantenuto il checkpoint CHR `20261023 1404 - 49 regions and 1 sectors`. Su una copia sono stati riconciliati congiuntamente i trade dei 16 Mining ancora da inserire, mantenendo output, baseline e CHR. Questa è una nuova assunzione sui prior commerciali, non una correzione di osservazioni empiriche certificate.

È stata usata la proiezione dei trade su budget di riga con domanda finale firmata già presente nella pipeline. L'obiettivo di questa sola riconciliazione è quadratico ponderato; **l'obiettivo del modello MRIO rimane KL**. Per la riconciliazione sono stati selezionati esplicitamente Gurobi e due thread, senza fallback. I pesi delle fonti rimangono quelli della policy: paired 1, direct 0,5, composite 0,2, imputed 0,1.

La prova registra:

- 37,632 target bilaterali esteri per i 16 settori, inclusi 28,536 zeri espliciti.
- 29,349 rotte prima omesse: nel fit hanno un prior debole pari a zero e possono aumentare se necessario; successivamente il risultato diventa un target esplicito dello scenario.
- 2,961 rotte con variazione oltre 1 USD.
- **15.466981 miliardi USD** di variazioni assolute sommate sulle rotte (circa 5,4% del trade Mining iniziale, 288,263 miliardi USD).
- Trade totale dei 16 Mining da circa **288,263** a **298,992 miliardi USD**. Il cambiamento lordo comprende aumenti e diminuzioni, non è una perdita netta.
- Aumento massimo su una rotta: **2254.215107 milioni USD**; riduzione massima **565.518167 milioni USD**. Sono variazioni economiche sostanziali, da valutare.

Output, inventari tecnici, piano dei passi e trade degli altri 50 settori sono rimasti invariati in questa riconciliazione. È stato riscritto solo il foglio `Trades` della copia. Restano le correzioni dei 37 profili di V già documentate nel tentativo precedente, applicate su copie e conservando il totale netto di V.

## Modifiche alla sola pipeline

1. `ChildTargets.select` permette di limitare il controllo dei budget ai settori effettivamente previsti dalla prova.
2. `run_model_trial.py` controlla i gruppi fino a `stop_after_step`: gli altri 50 settori non bloccano una prova Mining.
3. `fit_row_trade` accetta Gurobi come scelta esplicita per verifica e riconciliazione; la precedente politica open source rimane disponibile quando non è specificato un solver.
4. `reconcile_checkpoint_trade.py` riconcilia tutti i fratelli pendenti insieme, conserva i file originali e scrive tutte le rotte estere, inclusi gli zeri stimati. Nella prova MCU sono stati verificati **2.352 vincoli commerciali esteri attivi su 2.352 rotte**; sono escluse solo le 49 diagonali domestiche.
5. Il driver prevede un settore per processo, salvataggio dopo ogni successo e arresto al primo fallimento. La prosecuzione automatica non è arrivata a COB perché MCU non è stato accettato.

I controlli mirati, comprendenti solver Gurobi, fratelli con budget condivisi, dati mancanti, domanda finale negativa e selezione dei settori, sono passati: **23 test**. Nessuna modifica è stata fatta a MARIO o CVXLab durante questa continuazione; restano le modifiche precedenti già presenti nei rispettivi worktree. Nessun commit o push in questo tentativo.

## Risultato del modello completo

Il controllo dei budget dei 16 Mining riconciliati passa. La verifica di fattibilità del problema completo con Gurobi restituisce **optimal**, con circa 759.990 variabili, 3.940.109 vincoli CVXPY e 4.556.747 righe native. Il massimo residuo misurato nel problema scalato è circa 2e-9, cioè circa **2 USD** con la scala e le unità usate: è una verifica numerica, non una prova simbolica di fattibilità esatta.

Il modello KL è quindi stato chiamato con **MOSEK**, due thread e gli stessi parametri del checkpoint (tolleranze coniche 1e-10, solve form duale). Dopo **30,98 secondi dell'ottimizzatore**, MOSEK ha terminato con **Problem status UNKNOWN e Solution status UNKNOWN**. CVXPY ha sollevato `SolverError`. L'intera prova MCU, compresa preparazione e compilazione, è durata circa **191.76 secondi**.

Questo stato non certifica infeasibilità e non è una soluzione `optimal` con piccoli negativi da ripulire. La regola autorizzata di accettare e ripulire le soluzioni optimal non si può applicare a un punto che CVXPY non ha restituito come soluzione. Non è stata abbassata una soglia per ottenere artificialmente uno stato accettato e non sono stati provati altri solver o funzioni obiettivo.

La riconciliazione ha quindi rimosso il precedente blocco dei budget e ha permesso di raggiungere la vera ottimizzazione KL. Resta un arresto numerico di MOSEK da analizzare separatamente. Non c'è un database MCU esportato e non sono stati tentati gli altri 15 Mining.

## Risorse e limiti della misura

La sola riconciliazione è durata circa 22,90 secondi, con footprint massimo osservato di circa 1,28 GiB. Durante MCU il monitoraggio si è interrotto prima della fine, mentre il processo figlio ha completato e scritto log e manifest. Il massimo osservato fino a quel momento è **5.94 GiB**, che è soltanto un limite inferiore al picco effettivo. Non va usato come stima della RAM finale o come confronto completo con CHR. Non risultano processi di questa prova ancora attivi al controllo finale.

## Riproducibilità

La cartella condivisa di questo tentativo contiene gli input e la diagnostica, **nessun database accettato**:

`/Users/lorenzorinaldi/Library/CloudStorage/OneDrive-SharedLibraries-WSPO365/RCD-Entice-EXT - Documents/General/2.Deliverables and Milestones/WP2. Improved data and empirics on trade and climate/Data split/Inventories/D2.8 inventories/20261023 1642 - 49 regions and 2 sectors`

Gli audit della riconciliazione sono in `diagnostics/trade_reconciliation/`. `exact_trial_inputs.zip` conserva i due Excel esatti usati dal processo, con verifica degli hash prima della consegna; i metadati applicati dal servizio cloud ai file Excel esterni all'archivio non alterano questa copia. Il log completo, `feasibility.json`, la configurazione e `failure.json` permettono di distinguere la fattibilità lineare dall'arresto dell'ottimizzatore KL. `resource-completeness.json` esplicita i limiti del monitoraggio.

Il primo avvio della sola riconciliazione aveva selezionato l'interprete Anaconda generale invece dell'ambiente MARIO e si è fermato durante gli import; il log è conservato localmente. La riconciliazione eseguita e la prova MRIO usano `/opt/anaconda3/envs/mario/bin/python`. Non ci sono state ottimizzazioni MRIO aggiuntive per questo errore di avvio.
