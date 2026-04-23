FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ARG SHIPPER_REF=main
WORKDIR /opt

RUN git clone --depth 1 --branch "${SHIPPER_REF}" \
        https://github.com/rwb-truelime/n8n-langfuse-shipper.git \
        /opt/shipper \
    && cd /opt/shipper \
    && python -c "import pathlib, re; \
p = pathlib.Path('src/n8n_langfuse_shipper/models/n8n.py'); \
s = p.read_text(); \
s = s.replace('from pydantic import BaseModel, Field', 'from pydantic import BaseModel, Field, field_validator'); \
s = re.sub(r'(    source: Optional\\[List\\[NodeRunSource\\]\\] = None\\n)', r'\\1\\n    @field_validator(\"source\", mode=\"before\")\\n    @classmethod\\n    def _filter_none_sources(cls, v):\\n        if isinstance(v, list):\\n            return [x for x in v if x is not None]\\n        return v\\n', s); \
p.write_text(s); \
assert 'field_validator' in s and '_filter_none_sources' in s, 'patch failed'" \
    && pip install --no-cache-dir .

WORKDIR /opt/shipper
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
