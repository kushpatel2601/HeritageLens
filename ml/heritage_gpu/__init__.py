"""HeritageLens GPU worker.

A pull-based worker that turns a free Colab GPU into an elastic accelerator for the HeritageLens
archive: it registers with the API, leases jobs it has engines for, heartbeats while working, fetches
inputs by storage key, uploads 3D artifacts and reports schema-checked results - all over outbound
HTTPS, so it runs behind NAT with no inbound ports.
"""

__version__ = "0.1.0"
