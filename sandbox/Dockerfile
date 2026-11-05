FROM python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337

ENV HOME=/nonexistent PATH=/usr/local/bin:/usr/bin:/bin
WORKDIR /work
COPY --chown=0:0 sandbox/launcher.py /opt/sandbox/launcher.py
RUN chmod 0555 /opt/sandbox && chmod 0444 /opt/sandbox/launcher.py

USER 65532:65532
ENTRYPOINT ["python", "-I", "-B", "-u", "/opt/sandbox/launcher.py"]
