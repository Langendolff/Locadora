# Instalação

A Locadora roda em containers Docker. O jeito mais fácil é baixar o pacote do seu sistema na
página de **[Releases](https://github.com/Langendolff/Locadora/releases/latest)**. Cada pacote
traz um `LEIA-ME.txt` com o passo a passo.

Em qualquer sistema, tenha à mão o **arquivo WireGuard (.conf)** de uma VPN que permita P2P
([como gerar na ProtonVPN](configuracao.md#protonvpn-recomendado-plano-pago)).

## Windows 10/11

**Requisitos:** WSL2 e Docker Desktop.

1. PowerShell como administrador → `wsl --install` → reinicie. Abra o Ubuntu uma vez e crie seu usuário.
2. Instale o [Docker Desktop](https://www.docker.com/products/docker-desktop/) e ative
   **Settings → Resources → WSL integration** para o Ubuntu.
3. Baixe `Locadora-vX.Y.Z-windows.zip`, extraia e clique duas vezes em **`Instalar.bat`**.

O instalador copia a Locadora para dentro do Linux do WSL (`~/Locadora`), onde o disco é rápido
e os hardlinks funcionam. Lá, ela é a mesma instalação do Linux: `cd ~/Locadora && ./setup.sh`.

## macOS

**Requisito:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) rodando.

1. Baixe `Locadora-vX.Y.Z-macos.zip` e extraia.
2. Clique duas vezes em **`Instalar.command`**. Se o macOS bloquear: botão direito → **Abrir** → **Abrir**.

No Mac não há aceleração de vídeo por GPU no Jellyfin (o Docker Desktop não repassa a GPU).

## Linux

**Requisito:** Docker com o plugin `compose`, e seu usuário no grupo `docker`.

```bash
git clone https://github.com/Langendolff/Locadora.git
cd Locadora
./setup.sh ~/Downloads/sua-vpn.conf
```

Ou baixe `Locadora-vX.Y.Z-linux.tar.gz` dos Releases e rode o mesmo `./setup.sh`.
Com GPU Intel/AMD, o Jellyfin usa aceleração de vídeo automaticamente.

## Docker nativo × Docker Desktop

O `setup.sh` detecta qual está em uso:

| | Docker nativo (Linux) | Docker Desktop (macOS, Windows, Linux) |
|---|---|---|
| VPN (`/dev/net/tun`) | do sistema | da VM do Docker |
| GPU no Jellyfin | sim (Intel/AMD) | não |
| Desempenho de disco | nativo | bom no WSL e no macOS (VirtioFS) |

## Atualizar

Baixe a versão nova e rode o instalador de novo (ou `git pull && ./setup.sh`). Configurações,
senha e biblioteca são mantidas.
