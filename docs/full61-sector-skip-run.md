# GTAP a 61 regioni: piano di 69 attività con salto dei settori non riusciti

Rapporto interno ENTICE. Avvio: `2026-10-28T16:54:52.614269+00:00`. Il nome delle cartelle usa questo stesso istante anche per un risultato parziale.

## Risultato effettivo

La prova comprende un piano di **69 attività ENTICE**, da tentare una alla volta, su una baseline GTAP Power 2023 di **61 regioni e 76 settori**. Sono state accettate **52 attività**; il database risultante ha **128 settori**, di cui i parent residui rimangono presenti. Completare tutte le attività avrebbe portato a 145 settori.

- Completate: CHR, COB, GRA, LIT, MAN, MAO, MIO, MUR, NIK, NIO, PGM, REE, SIL, AGT, COR, CRR, HYE, ISS, KFR, LCO, LFP, LIR, LMO, MNR, MSI, MTH, NCA, NCM, NFR, NIR, NMC, PCP, PFR, PLR, RER, SCI, SDH, SOP, TIR, TVP, WNT, ZIR, APP, BVH, BVL, CPS, GAR, HEL, PGR, PLP, BAR, SGI.
- Ancora aggregate nel parent: APS, CEM, CPP, HVC, ICH, ICL, MCU, MGC, MUN, PLSR, RAL, RBR, RCP, SDG, SIR, TIT, ZIN.
- Gruppi falliti o bloccati: 17; interrotti dal supervisore: 0.
- Attività mai tentate: nessuna.
- Esito del processo: `completed`; motivo di arresto: `None`.
- Eventuale errore globale registrato dal runner: nessuno.

La prima fase si era fermata a 17 attività aggiunte per un limite prudenziale di 12 GiB. Su indicazione dell’utente la prova è stata ripresa da ISS, senza rifare i settori già accettati né ritentare i sei già rinviati. L’ordine degli step è stato adattato per completare i 46 ancora da eseguire; tutti gli altri componenti del workbook, inclusi inventari, output e trade, sono byte per byte identici. Il primo tentativo interrotto di ISS resta nel giornale delle interruzioni precedenti.

Dopo 50 attività aggiunte, RBR si era fermato prima dei solver: in DZL il target superava il residuo RPP di 1,42e-12 M USD, circa 0,0000014 USD. Il controllo MARIO usava un confronto esatto, senza considerare gli arrotondamenti delle precedenti sottrazioni dei fratelli. La correzione usa lo stesso limite di errore in virgola mobile nel confronto iniziale e nella pulizia del residuo, includendo le allocazioni già avvenute. I target originali restano identici; solo un residuo negativo entro questo limite numerico viene posto a zero. Gli eccessi sostanziali continuano a essere respinti. I 38 test mirati sono passati. La terza fase riprende gli ultimi cinque settori dal checkpoint PLP; nessuna formulazione, peso, dominio o impostazione del solver è cambiata e CVXLab è rimasto intatto.


Un settore saltato non viene cancellato dal database: la sua attività rimane nel parent. Non si redistribuiscono i suoi target agli altri figli. Questo risultato non equivale a una disaggregazione completa delle 69 attività se ne rimangono pendenti. **E deve essere ricalcolata**; l'esito numerico non sostituisce la successiva valutazione economica.

I rinvii sono distinti per fase:

- Verifica preliminare dichiarata infeasible: MCU, HVC, ICH, ICL, RAL.
- Verifica preliminare ottima, ma nessun risultato finale accettato: MGC, TIT, ZIN, CEM, SDG, APS, CPP, MUN, PLSR, RBR, RCP, SIR.
- Altri rinvii: nessuno.

La seconda categoria richiede di esaminare convergenza, precisione e condizioni del problema principale. Il solo rinvio non dimostra un'impossibilità economica del settore; la verifica preliminare usa inoltre tolleranze diverse da quelle del problema principale, descritte sotto.

## Geografia e copertura settoriale

Le 61 regioni derivano direttamente dalle 163 regioni native, con sole aggregazioni. I 64 gruppi desiderati sono stati raccordati alle unità territoriali indivisibili di GTAP: nessuna regione nativa è stata disaggregata. Il raccordo e le eccezioni sono in `Classifications/GTAP model regions` e nel documento `gtap-model-regions.md` della repository.

Il piano conserva i precedenti 67 codici, ricostruisce PCP con i dati dei coal products e aggiunge BAR e SGI. Sono esclusi AMM, HYS e una nuova attività estrattiva del silicio, come concordato. MSI rimane nel piano. Il workbook originale contiene **4.209 profili regionali (69 × 61)**: resta completo anche quando il risultato ne include solo una parte.

## Modello e gestione dei fallimenti

È stata usata la formulazione **quadratica**, `Split_sectors_MRIO_quadratic`, con **Gurobi**, riprendendo le impostazioni della prova riuscita a 13 regioni. Questa prova non dimostra la scalabilità di KL. Nessun cambio automatico di obiettivo, solver o dati è avvenuto durante la sequenza.

Le impostazioni includono accounting inherit, peso domanda finale 0,1, peso offerta 1, scala 1.000, vincoli compatti e rinvio del ricalcolo di E. Gurobi usa due thread e le proprie tolleranze di convergenza predefinite; la verifica preliminare affine usa ancora una banda più stretta, pari a circa 1 USD nelle unità originali.

MARIO esegue `add_sectors(..., intermediate_steps=True, on_step_failure="continue")`: compila ogni gruppo sulla classificazione effettivamente raggiunta, lavora su una copia e conserva soltanto il risultato accettato. Un fallimento di ottimizzazione riconosciuto conserva il checkpoint precedente e fa avanzare al gruppo successivo. La passata non ritenta i gruppi falliti; ISS è stato ripreso dopo l'interruzione prudenziale, che non aveva prodotto una soluzione. Non è stato avviato un ciclo di aggiustamenti per forzare il successo. Errori di integrità o programmazione restano errori che fermano l'esecuzione.

La proiezione degli inventari dei settori assenti verso i parent è svolta da MARIO. I dati sorgente non vengono armonizzati nuovamente fra uno step e l'altro. L'esclusione di un settore dal risultato non richiede di rigenerare i file di raccolta dati.

I punti `optimal` seguono la politica già concordata di pulizia dei segni vietati in post-processing e diagnostica monetaria non bloccante. Non è stata introdotta una nuova soglia in dollari per respingere una soluzione ottima. Un esito `infeasible` della verifica preliminare o un esito non ottimale del solver sono casi distinti: non sono una bocciatura a posteriori di un punto `optimal`. In particolare MCU si è fermato alla verifica preliminare, mentre MGC l'ha superata ma il problema principale ha restituito `user_limit`. Non ne segue che i settori siano impossibili in assoluto.

## Preparazione e armonizzazione, prima dei solver

La pipeline ha riutilizzato lettura delle fonti, preparazione degli output e del trade e costruzione dei profili già esistenti. Le tre attività aggiunte o ricostruite usano i lettori e le regole di selezione dei profili già previsti per i dati raccolti; donatori e fallback sono tracciati nell'audit. Gli output vengono riconciliati insieme e successivamente il trade viene proiettato congiuntamente sui budget residui dei parent, per tutti i 69 settori.

La riconciliazione finale del trade ha modificato **14,458 rotte per oltre 1 USD**. La somma delle variazioni assolute è **237,339.122 M USD**, circa **237.34 miliardi USD**. La variazione massima positiva su una cella è 14,183.130 M USD, quella negativa 1,002.835 M USD. È una modifica sostanziale dei prior di trade, non semplice pulizia numerica; la somma assoluta non rappresenta una variazione netta del commercio mondiale.

Output e baseline rimangono invariati in questa proiezione. Le rotte estere preparate, inclusi gli zeri, sono esplicitate per preservare i budget dei fratelli successivi: sono target di scenario riconciliati, non nuove osservazioni indipendenti o zeri empiricamente certificati. Il superamento dei budget è stato verificato prima della sequenza; questo controllo non certifica da solo la fattibilità del modello MRIO completo.

La prima proiezione si era fermata per un eccesso di circa **0,0005 USD** causato dalla serializzazione Excel: il controllo ora usa almeno la banda di tolleranza dei budget già esistente. Non è una correzione ai target. Un primo tentativo di preparazione e un avvio preliminare erano terminati prima dei solver; non sono ulteriori prove economiche.

## Memoria e tempi misurati

La preparazione ha richiesto circa **249 secondi** e un picco di **2,42 GiB**. Il processo del modello ha richiesto **7.85 ore**, con picco di impronta fisica di **17.38 GiB** e RSS di **7.99 GiB**. I campioni misurano l'albero dei processi del modello; non tutta la memoria delle altre applicazioni del Mac. Non vanno sommati i due picchi, che misurano aspetti diversi e possono avvenire in istanti diversi.

La durata somma le fasi di esecuzione monitorate e non include l'attesa fra la prima interruzione e la ripresa. I singoli record delle fasi sono conservati nella provenienza; i campioni della seconda fase e quelli della prima sono distinti.

Il Mac dispone di **18 GiB di RAM fisica**. Dal monitoraggio aggiuntivo, avviato durante la seconda fase, il picco di swap usato dall’intero sistema è **0.00 GiB**; all’avvio del monitor era 0.00 GiB. Include anche le altre applicazioni e non rappresenta da solo un fabbisogno attribuibile a MARIO. I campioni sono nella provenienza.

Il limite iniziale di 12 GiB era prudenziale e non rappresentava un esaurimento della RAM fisica. Dopo l'indicazione dell'utente è stato rimosso per la ripresa. Le soglie di guardia della seconda fase sono 64 GiB per l'impronta, 32 GiB per RSS, 12 ore per la ripresa e 8 GiB di spazio libero minimo. Non sono RAM riservata: il sistema operativo gestisce RAM, compressione e swap. Un arresto per risorse resta distinto dall'infattibilità matematica.

Il tempo complessivo comprende compilazione, verifica preliminare, ottimizzazione e scrittura dei checkpoint/inventari. I tempi del solver principale e del solver della verifica preliminare sono separati in `diagnostics/step-statistics.json`; non devono essere confusi con il tempo di uno step completo. Questa misura vale per **un nuovo settore per problema e 61 regioni**, con crescita della classificazione nel corso della sequenza. Non è la RAM per risolvere tutti i figli insieme né una misura diretta di KL o di 163 regioni.

## Controlli sul risultato

Gli hash della baseline e del workbook sorgente sono verificati prima della pubblicazione; i checkpoint accettati e i fingerprint dei rispettivi profili sono controllati contro lo stesso piano completo. La rinomina dei residui è reversibile e il database ricaricato riporta matrici identiche prima e dopo la normalizzazione dei codici. I parent vengono rinominati solo quando un loro figlio è stato effettivamente aggiunto. Se PCP è riuscito, PCP è Coal products e P_C è Petroleum products.

Le copie Excel nella libreria condivisa possono acquisire metadati Office e relazioni verso questi metadati. Il controllo di pubblicazione conserva tali aggiunte e verifica che fogli, dati, stili, classificazioni e relazioni originali rimangano intatti. Hash dell'originale e della copia pubblicata sono distinti nell'audit; l'originale esatto è conservato dentro `diagnostics/exact-inputs.zip`.

La seguente riaggregazione cumulativa confronta il database finale ricondotto ai parent originali con l'esatta baseline a 61 regioni, senza usare una soglia monetaria come criterio di rifiuto:

| Blocco | Massima differenza assoluta (USD) | Somma differenze assolute (M USD) |
|---|---:|---:|
| Z | 1,611.769 | 0.043382 |
| Y | 0.855 | 0.000099 |
| V | 0.674 | 0.000009 |
| X | 0.000 | 0.000000 |
| EY | 0.000 | 0.000000 |
| VY | 0.000 | 0.000000 |

Queste differenze sono diagnostiche contabili, non un benchmark completo della plausibilità economica. E è esclusa perché da ricalcolare. Il risultato contiene anche la baseline esatta in `baseline/` per i confronti successivi.

## Modifiche apportate e tracciabilità

- **MARIO:** gestione generica dei salti già implementata e testata; nella terza fase è stato corretto soltanto il controllo sugli arrotondamenti cumulati dell’output e la corrispondente pulizia del residuo. La formulazione di ottimizzazione è invariata. Codice e test della correzione sono archiviati nella provenienza.
- **Database disaggregation:** nuovo preparatore del piano completo a 61 regioni; inoltro del flag `--on-step-failure` al metodo MARIO quando si selezionano opzioni e solver fissi; delega delle fonti country-component ai metodi trade esistenti; correzione del controllo numerico della proiezione dei budget. Policy di fallback più continue non è combinata automaticamente: la CLI lo rifiuta per evitare due controllori concorrenti.
- **CVXLab:** nessuna modifica.
- **Verifiche:** 44 test della funzione di salto MARIO nella fase precedente; in questa preparazione 22 test additional-sector/reconciliation e 22 test checkpoint-trade/parent-budgets/shared-runs superati. Nessuna nuova batteria di prove del modello è stata avviata dopo i fallimenti dei singoli settori.

La cartella `diagnostics/` conserva report per tentativo, opzioni, audit delle fonti e del trade, campioni di memoria, log e archivio degli input compilati. `provenance/` conserva i sorgenti effettivamente usati e i loro hash: i worktree erano già modificati, quindi il solo commit Git non sarebbe sufficiente a riprodurre questa prova. La cartella Inventories conserva l'intero workbook, l'ultimo step riuscito e il rimanente: il numero nel nome della cartella conta le attività effettivamente riuscite, non limita il piano sorgente.

## Giornale della singola passata

| Step | Attività | Esito | Nota |
|---:|---|---|---|
| 1 | CHR | accepted |  |
| 2 | COB | accepted |  |
| 3 | GRA | accepted |  |
| 4 | LIT | accepted |  |
| 5 | MAN | accepted |  |
| 6 | MAO | accepted |  |
| 7 | MCU | failed | Linear split feasibility check returned infeasible; see feasibility.json. |
| 8 | MGC | failed | CVXLab split optimization did not solve optimally. Check the generated model directory for details. |
| 9 | MIO | accepted |  |
| 10 | MUR | accepted |  |
| 11 | NIK | accepted |  |
| 12 | NIO | accepted |  |
| 13 | PGM | accepted |  |
| 14 | REE | accepted |  |
| 15 | SIL | accepted |  |
| 16 | TIT | failed | CVXLab split optimization did not solve optimally. Check the generated model directory for details. |
| 17 | ZIN | failed | Solver 'GUROBI' failed. Try another solver, or solve with verbose=True for more information. |
| 18 | AGT | accepted |  |
| 19 | CEM | failed | CVXLab split optimization did not solve optimally. Check the generated model directory for details. |
| 20 | COR | accepted |  |
| 21 | CRR | accepted |  |
| 22 | HVC | failed | Linear split feasibility check returned infeasible; see feasibility.json. |
| 23 | HYE | accepted |  |
| 24 | ISS | accepted |  |
| 25 | KFR | accepted |  |
| 26 | LCO | accepted |  |
| 27 | LFP | accepted |  |
| 28 | LIR | accepted |  |
| 29 | LMO | accepted |  |
| 30 | MNR | accepted |  |
| 31 | MSI | accepted |  |
| 32 | MTH | accepted |  |
| 33 | NCA | accepted |  |
| 34 | NCM | accepted |  |
| 35 | NFR | accepted |  |
| 36 | NIR | accepted |  |
| 37 | NMC | accepted |  |
| 38 | PCP | accepted |  |
| 39 | PFR | accepted |  |
| 40 | PLR | accepted |  |
| 41 | RER | accepted |  |
| 42 | SCI | accepted |  |
| 43 | SDG | failed | Solver 'GUROBI' failed. Try another solver, or solve with verbose=True for more information. |
| 44 | SDH | accepted |  |
| 45 | SOP | accepted |  |
| 46 | TIR | accepted |  |
| 47 | TVP | accepted |  |
| 48 | WNT | accepted |  |
| 49 | ZIR | accepted |  |
| 50 | APP | accepted |  |
| 51 | APS | failed | CVXLab split optimization did not solve optimally. Check the generated model directory for details. |
| 52 | BVH | accepted |  |
| 53 | BVL | accepted |  |
| 54 | CPP | failed | CVXLab split optimization did not solve optimally. Check the generated model directory for details. |
| 55 | CPS | accepted |  |
| 56 | GAR | accepted |  |
| 57 | HEL | accepted |  |
| 58 | ICH | failed | Linear split feasibility check returned infeasible; see feasibility.json. |
| 59 | ICL | failed | Linear split feasibility check returned infeasible; see feasibility.json. |
| 60 | MUN | failed | CVXLab split optimization did not solve optimally. Check the generated model directory for details. |
| 61 | PGR | accepted |  |
| 62 | PLP | accepted |  |
| 63 | PLSR | failed | CVXLab split optimization did not solve optimally. Check the generated model directory for details. |
| 64 | RAL | failed | Linear split feasibility check returned infeasible; see feasibility.json. |
| 65 | RBR | failed | CVXLab split optimization did not solve optimally. Check the generated model directory for details. |
| 66 | RCP | failed | CVXLab split optimization did not solve optimally. Check the generated model directory for details. |
| 67 | SIR | failed | CVXLab split optimization did not solve optimally. Check the generated model directory for details. |
| 68 | BAR | accepted |  |
| 69 | SGI | accepted |  |
