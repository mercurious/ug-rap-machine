#!/bin/sh
# Install the Underground Rap Machine on a Retroid Pocket Flip 2 running ROCKNIX, over ssh.
#   flip2/install.sh [ssh-host]        default host: flip2-12g
# Needs Donkey (https://github.com/mercurious/donkey) on the device: $DONKEY_HOME, the launcher its
# Donkey.sh port entry runs, or /storage/apps/donkey. Copies the app to /storage/apps/rap-machine with
# the controller profile and the Firefox prefs for the app's own Donkey profile (Web Audio may start
# without a tap so the page can be driven over ssh; the mic is allowed without a prompt), and adds the
# "Rap Machine" and "Rap Machine + Gemma" ports. The Gemma port needs Retro Voice Chat's llamatalk kit
# and models on the device; without them it runs like the plain one and the MC panel says what is missing.
set -eu
HOST=${1:-flip2-12g}
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
APP=/storage/apps/rap-machine

# Same lookup as launch.sh.
ssh "$HOST" sh -s <<'EOF'
D=${DONKEY_HOME:-}
if [ -z "$D" ] && [ -f /storage/roms/ports/Donkey.sh ]; then
  D=$(sed -n 's|.*"\(/[^"]*\)/launch\.sh".*|\1|p' /storage/roms/ports/Donkey.sh | head -n 1)
fi
D=${D:-/storage/apps/donkey}
[ -x "$D/launch.sh" ] || { echo "Donkey not found at $D/launch.sh; install it first: https://github.com/mercurious/donkey" >&2; exit 1; }
echo "Donkey at $D"
EOF
ssh "$HOST" "mkdir -p $APP/logs /storage/roms/ports"
scp -q "$ROOT/underground-rap-machine.html" "$HERE/server.py" "$HERE/launch.sh" "$HERE/rap-machine.yaml" "$HERE/rap-machine.prefs" "$HOST:$APP/"
scp -q "$HERE/Rap Machine.sh" "$HERE/Rap Machine + Gemma.sh" "$HOST:/storage/roms/ports/"
ssh "$HOST" "chmod +x $APP/launch.sh $APP/server.py '/storage/roms/ports/Rap Machine.sh' '/storage/roms/ports/Rap Machine + Gemma.sh'
  GL=/storage/roms/ports/gamelist.xml
  if [ -f \$GL ]; then
    python3 - <<'EOF'
p='/storage/roms/ports/gamelist.xml'; s=open(p).read()
desc='Generates a beat in one of four lanes (GLITTER, JERK, CHE, PRTTIFUN) and auto-tunes the mic over it. A B X Y and the d-pad hit the pads, Start plays, Select rolls a new beat, the left stick picks the scene, L1/R1 change the view, L3 is the mic, R3 records. The stick rings follow the beat and your voice.'
ports=[('Rap Machine.sh', 'Underground Rap Machine', desc),
       ('Rap Machine + Gemma.sh', 'Underground Rap Machine + Gemma', desc + ' This one also starts Gemma and Pocket TTS so the MC panel can play the machine; it needs the llamatalk kit and models from Retro Voice Chat.')]
added=[]
for path, name, d in ports:
    if path in s: continue
    s=s.replace('</gameList>', '\t<game>\n\t\t<path>./%s</path>\n\t\t<name>%s</name>\n\t\t<desc>%s</desc>\n\t</game>\n</gameList>' % (path, name, d)); added.append(name)
if added: open(p,'w').write(s); print('gamelist.xml: added ' + ', '.join(added))
EOF
  fi
  echo installed to $APP"
