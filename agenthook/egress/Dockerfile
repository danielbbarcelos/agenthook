# Egress broker image — stdlib only, no pip deps, so it stays tiny and has a
# minimal attack surface. Built as `agenthook/egress:latest`.
FROM python:3.12-slim
COPY broker.py /broker.py
# Data plane (gateway + forward proxy) and control plane.
EXPOSE 8080 8079
ENTRYPOINT ["python", "-u", "/broker.py"]
