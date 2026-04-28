FROM langgenius/dify-api:1.13.3

USER root

COPY railway-entrypoint.sh /railway-entrypoint.sh
RUN chmod +x /railway-entrypoint.sh

ENTRYPOINT ["/bin/bash", "/railway-entrypoint.sh"]
