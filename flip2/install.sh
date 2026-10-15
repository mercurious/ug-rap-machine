#!/bin/sh
# Install the Underground Rap Machine on a Retroid Pocket Flip 2 running ROCKNIX, over ssh.
#   flip2/install.sh [ssh-host]        default host: flip2-12g
# Needs the house Firefox at /storage/apps/firefox-rocknix on the device. Copies the app to
# /storage/apps/rap-machine, adds the "Rap Machine" and "Rap Machine + Gemma" ports, allows the mic
# for the app's origin in the Firefox profile, and lets Web Audio start without a tap so the page can be
# driven over ssh. The Gemma port needs Retro Voice Chat's llamatalk kit and models on the device; without
# them it runs like the plain one and the MC panel says what is missing.
set -eu
HOST=${1:-flip2-12g}
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
APP=/storage/apps/rap-machine

ssh "$HOST" "mkdir -p $APP/logs /storage/roms/ports"
scp -q "$ROOT/underground-rap-machine.html" "$HERE/server.py" "$HERE/launch.sh" "$HERE/rap-machine.yaml" "$HOST:$APP/"
scp -q "$HERE/Rap Machine.sh" "$HERE/Rap Machine + Gemma.sh" "$HOST:/storage/roms/ports/"
ssh "$HOST" "chmod +x $APP/launch.sh $APP/server.py '/storage/roms/ports/Rap Machine.sh' '/storage/roms/ports/Rap Machine + Gemma.sh'
  python3 $APP/server.py --grant-mic
  UJ=/storage/.mozilla/firefox-rocknix/user.js
  if [ -f \$UJ ] && ! grep -q 'media.autoplay.block-webaudio' \$UJ; then
    printf '%s\n' '' '// Rap Machine (2026-10-14): Web Audio may start before the first tap, so the app can be driven' \
      '// over ssh for testing (flip2/server.py --key). The app itself still only starts audio on a button.' \
      'user_pref(\"media.autoplay.block-webaudio\", false);' >> \$UJ
    echo 'user.js: web audio autoplay allowed'
  fi
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
