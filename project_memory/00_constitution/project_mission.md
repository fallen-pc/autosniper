# Project Mission

AutoSniper exists to monitor Australian vehicle-auction inventory, normalize and govern the data, and surface decision-ready listings in the dashboard and operator tools.

The project is not allowed to rely on chat memory as its source of truth. Durable project memory must live in the repo, survive resets, and be loadable by a fresh agent with no prior conversation.

Long-term success means:

- the app is runnable and explainable by a fresh operator
- valuation and profit logic stay consistent across code, UI, and governance
- new curves can be added without breaking dataset contracts or hidden rules
- high-sensitivity files and decisions do not drift because an agent guessed
