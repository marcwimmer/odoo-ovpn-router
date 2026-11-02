# WireGuard-Paket auf dem VPN-Server ablegen

Für Zielsysteme, auf denen jemand anderes installiert (z. B. ein Dienstleister) und
kein kurzlebiger Link mit Schlüssel-Registrierung passt.

## Ablauf

1. Member auf **Auslieferungsart „Linux / macOS – Install-Script, Schlüssel kommt vom
   Server“** stellen. Dabei erzeugt Odoo wie bisher einmalig das Schlüsselpaar
   (vorhandener Mechanismus, kein neuer).
2. **Apply to VPN Server**, damit der Peer mit dem neuen Public Key auf dem
   WireGuard-Server steht.
3. Button **„Paket auf Server ablegen“**. Odoo schreibt
   `<Paketverzeichnis>/member-<ID>-<Name>/install.sh` und `README.txt`.
4. Der Admin des Zielsystems kopiert den Ordner per SSH vom VPN-Server (braucht dort
   root bzw. sudo) und startet auf dem Zielsystem als root `bash install.sh`, wann
   immer es passt. Danach die Kopie löschen.

## Installer

- Erzeugt **keinen** Schlüssel und registriert nichts, die Config ist fertig im Paket.
- Beliebig oft startbar:
  - gleiche Config schon installiert → keine Änderung, Interface wird nur
    hochgefahren, falls es nicht läuft;
  - andere Config vorhanden → **Abbruch mit Exit-Code 3**, nichts geändert;
    bewusstes Ersetzen mit `bash install.sh --force` (alte Datei wird als
    `.bak-<Zeitstempel>` gesichert);
  - WireGuard wird nur installiert, wenn `wg-quick` fehlt.
- Gibt die Config nicht aus (sie enthält den privaten Schlüssel).
- Ob die Verbindung steht: `wg show <interface>`, Zeile „latest handshake“.

## Ablageort und Rechte

| Systemparameter | Bedeutung | Standard |
|---|---|---|
| `ovpn.wg_package_dir` | Verzeichnis, in das Odoo schreibt | `$OVPN_DATA/wg-packages` |
| `ovpn.wg_package_host_dir` | wie das Verzeichnis auf dem Host heißt (nur für die Anzeige) | wie oben |

- Verzeichnisse `0700`, `install.sh` `0700`, `README.txt` `0600`; Eigentümer ist der
  Odoo-Prozess (im Container root). Lesbar also nur für root/sudo auf dem VPN-Server.
- Der Ordnername hängt an der Member-ID; Sonderzeichen im Namen werden ersetzt.
  Symlinks und Pfade außerhalb des Paketverzeichnisses werden abgelehnt.
- Erneutes Ablegen bei unverändertem Schlüssel erzeugt identische Dateien.
- Nur Benutzer der Gruppe `ovpn.manager` dürfen Pakete ablegen.
- Das Paket ist ein Laufzeit-Artefakt und gehört in kein Git-Repo.

## Nicht enthalten

- Member mit wstunnel (TCP/443): Export wird abgelehnt, weil der wstunnel-Teil des
  Installers bei jedem Lauf Binärdatei und Dienst neu schreibt. Dafür weiter den
  Deploy-Link nutzen.
- Kein automatisches Aufräumen alter Pakete. Nach der Installation den Ordner auf dem
  VPN-Server löschen.
- Schlüsselwechsel (Rotation) bleibt ein bewusster Schritt am Member; danach erneut
  ablegen und mit `--force` installieren.
