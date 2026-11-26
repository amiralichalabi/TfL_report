# TfL disruption logger

Polls the TfL Unified API about every 5 minutes via GitHub Actions (tube, Elizabeth line, DLR, Overground, tram, bus, National Rail, river bus, cable car) and stores disruptions with first-seen time in `disruptions.csv` and `disruptions.db`.
