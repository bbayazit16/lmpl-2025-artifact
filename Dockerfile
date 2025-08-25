FROM python:3.12.3-slim

RUN apt-get update && apt-get install -y opam haskell-stack pkg-config

WORKDIR /evaluation

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY coq-setup.sh /tmp/coq-setup.sh
RUN chmod +x /tmp/coq-setup.sh && /tmp/coq-setup.sh

COPY install-hs-to-coq.sh /tmp/install-hs-to-coq.sh
RUN chmod +x /tmp/install-hs-to-coq.sh && /tmp/install-hs-to-coq.sh

COPY install-verdi.sh /tmp/install-verdi.sh
RUN chmod +x /tmp/install-verdi.sh && /tmp/install-verdi.sh

COPY . .

CMD ["bash"]