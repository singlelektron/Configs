"""Offline production bridge checks; opt-in private-bus policy test has no host access.

MOONLIT_TEST_PRIVATE_BUS=1 python3 -m unittest discover -s tests -p test_moonlit_desktopctl.py
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('moonlit_desktopctl', ROOT/'config/moonlit/desktopctl.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='moonlit-bridge-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.release = self.root/'release'
        self.target = self.release/'managed/niri/moonlit-session.json'
        self.target.parent.mkdir(parents=True)
        self.live = self.root/'live'
        self.live.mkdir(mode=0o700)
        self.legacy = self.root/'legacy.py'
        self.legacy.write_text('# pinned baseline\n')
        self.binary = self.root/'noctalia'
        self.binary.write_text('# executable fixture\n')
        self.value = dict(schema=1, kind='moonlit-live-session', phase='basic',
            legacy_desktopctl=str(self.legacy), legacy_sha256=self.sha(self.legacy),
            live_root=str(self.live), binary=str(self.binary), library_path=str(self.root/'lib'),
            bar_unit=m.BAR_UNIT, release=str(self.release), transaction=str(self.live/'transaction.json'))
        for name in ('config', 'state', 'data', 'cache'):
            (self.live/name).mkdir()
            self.value[name+'_dir'] = str(self.live/name)
        self.write_manifest()
        self.link = self.root/'deployed.json'
        self.link.symlink_to(self.target)
        self.environment = {'HOME':'/home/test', 'XDG_CONFIG_HOME':'/home/test/.config',
            'XDG_DATA_HOME':'/home/test/.local/share', 'XDG_STATE_HOME':'/home/test/.local/state',
            'XDG_CACHE_HOME':'/home/test/.cache', 'XDG_RUNTIME_DIR':str(self.root),
            'NIRI_SOCKET':str(self.root/'niri.sock'), 'WAYLAND_DISPLAY':'wayland-1',
            'DBUS_SESSION_BUS_ADDRESS':'unix:path=/real/session-bus', 'PIPEWIRE_REMOTE':'pipewire-0',
            'TERMINAL':'kitty', 'LANG':'zh_CN.UTF-8'}
        self.env_patch = mock.patch.dict(os.environ, self.environment, clear=True)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.niri = dict(pid=100, start=200, state='S')

    @staticmethod
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def write_manifest(self):
        self.target.write_text(json.dumps(self.value))
        (self.release/'manifest.json').write_text(json.dumps({'files':{
            'managed/niri/moonlit-session.json':self.sha(self.target)}}))

    def session(self):
        records = {key:dict(pid=300+i, start=400+i, state='S')
                   for i,key in enumerate(('runner','shell','system_proxy','session_proxy'))}
        records.update(niri=self.niri, NIRI_SOCKET=os.environ['NIRI_SOCKET'],
            WAYLAND_DISPLAY=os.environ['WAYLAND_DISPLAY'],
            DBUS_SESSION_BUS_ADDRESS='unix:path='+str(self.live/'session-bus'),
            DBUS_SYSTEM_BUS_ADDRESS='unix:path='+str(self.live/'system-bus'))
        (self.live/'session.json').write_text(json.dumps(records))
        return records

    def test_fixed_managed_symlink_and_direct_target_are_accepted(self):
        self.assertEqual(m.read_manifest(self.link), self.value)
        self.assertEqual(m.read_manifest(self.target), self.value)

    def test_copied_manifest_and_changed_target_fail_closed(self):
        copy = self.root/'copy.json'
        copy.write_bytes(self.target.read_bytes())
        with self.assertRaisesRegex(m.DesktopError, 'fixed release'):
            m.read_manifest(copy)
        self.target.write_text(self.target.read_text()+' ')
        with self.assertRaisesRegex(m.DesktopError, 'differs'):
            m.read_manifest(self.link)

    def test_pinned_legacy_mutation_and_escaped_config_are_rejected(self):
        self.legacy.write_text('# changed\n')
        with self.assertRaisesRegex(m.DesktopError, 'Pinned legacy'):
            m.read_manifest(self.link)
        self.value['legacy_sha256'] = self.sha(self.legacy)
        self.value['config_dir'] = str(self.root/'outside')
        self.write_manifest()
        with self.assertRaisesRegex(m.DesktopError, 'within'):
            m.read_manifest(self.link)

    def test_manifest_symlink_parent_and_world_write_are_rejected(self):
        self.target.chmod(0o666)
        with self.assertRaisesRegex(m.DesktopError, 'regular file'):
            m.read_manifest(self.link)
        self.target.chmod(0o644)
        alias = self.root/'release-alias'
        alias.symlink_to(self.release, target_is_directory=True)
        self.value['release'] = str(alias)
        self.write_manifest()
        with self.assertRaisesRegex(m.DesktopError, 'fixed release'):
            m.read_manifest(self.link)

    def test_environment_preserves_application_config_and_restricts_only_shell(self):
        self.value['binary'] = str(self.root/'runtime/usr/bin/noctalia')
        definitions = self.root/'runtime/usr/share/qalculate'
        definitions.mkdir(parents=True)
        os.environ['QALCULATE_DEFINITIONS_DIR'] = '/old-runtime/share/qalculate'
        env = m.shell_environment(self.value, 'session-proxy', 'system-proxy')
        for name in ('HOME','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_STATE_HOME','NIRI_SOCKET','WAYLAND_DISPLAY','LANG'):
            self.assertEqual(env[name], self.environment[name])
        self.assertEqual(env['XDG_CACHE_HOME'], self.value['cache_dir'])
        self.assertEqual(env['PIPEWIRE_REMOTE'], 'moonlit-basic-unavailable')
        self.assertEqual(env['DBUS_SESSION_BUS_ADDRESS'], 'session-proxy')
        self.assertNotIn('NOCTALIA_CACHE_HOME', env)
        self.assertEqual(os.environ['PIPEWIRE_REMOTE'], 'pipewire-0')
        self.assertIn('terminal', env['TERMINAL'])
        self.assertEqual(env['QALCULATE_DEFINITIONS_DIR'], str(definitions))
        self.assertEqual(os.environ['QALCULATE_DEFINITIONS_DIR'], '/old-runtime/share/qalculate')
        definitions.rmdir()
        self.assertNotIn('QALCULATE_DEFINITIONS_DIR',
                         m.shell_environment(self.value, 'session-proxy', 'system-proxy'))

    def test_manifest_capabilities_are_opt_in_and_reject_unknown_or_malformed_lists(self):
        self.assertEqual(m.capabilities(m.read_manifest(self.link)), frozenset())
        for selected in (['audio'], ['network','bluetooth'], ['audio','bluetooth','network']):
            self.value['capabilities']=selected
            self.write_manifest()
            self.assertEqual(m.capabilities(m.read_manifest(self.link)), frozenset(selected))
        for selected in ('audio', None, ['notifications'], ['session'], ['audio','audio'], [1], [{}]):
            self.value['capabilities']=selected
            self.write_manifest()
            with self.subTest(selected=selected),self.assertRaisesRegex(m.DesktopError,'capabilities'):
                m.read_manifest(self.link)

    def test_audio_capability_preserves_real_remote_or_default_without_weakening_buses(self):
        self.value['capabilities']=['audio']
        env=m.shell_environment(self.value,'session-proxy','system-proxy')
        self.assertEqual(env['PIPEWIRE_REMOTE'],'pipewire-0')
        self.assertEqual(env['DBUS_SESSION_BUS_ADDRESS'],'session-proxy')
        self.assertEqual(env['DBUS_SYSTEM_BUS_ADDRESS'],'system-proxy')
        del os.environ['PIPEWIRE_REMOTE']
        self.assertNotIn('PIPEWIRE_REMOTE',m.shell_environment(self.value,'session-proxy','system-proxy'))
        self.value['capabilities']=['network','bluetooth']
        self.assertEqual(m.shell_environment(self.value,'s','b')['PIPEWIRE_REMOTE'],'moonlit-basic-unavailable')

    def test_capabilities_grant_only_their_exact_device_service_and_keep_session_policy(self):
        base=m.proxy_commands(self.live,'session','system')
        for selected,expected in (([],[]),(['audio'],[]),(['network'],['org.freedesktop.NetworkManager']),
                (['bluetooth'],['org.bluez']),(['network','bluetooth'],['org.freedesktop.NetworkManager','org.bluez'])):
            with self.subTest(selected=selected):
                system,session=m.proxy_commands(self.live,'session','system',selected)
                self.assertEqual([arg for arg in system if arg.startswith('--talk=')],['--talk='+name for name in expected])
                self.assertFalse(any(arg.startswith('--own=') for arg in system))
                self.assertEqual(session,base[1])

    def test_safety_probe_never_requests_a_real_device_or_logind_operation(self):
        with mock.patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],1,'','Access denied')) as run:
            m.verify_proxy('proxy')
        command=run.call_args.args[0]
        self.assertEqual(command[3:8],['org.freedesktop.login1','/org/freedesktop/login1/moonlit_denied_probe',
            'org.freedesktop.DBus.Properties','Set','ssv'])
        self.assertIn('MoonlitDeniedProbe',command)

    def test_proxy_only_allows_read_devices_and_explicit_player_transport(self):
        system, session = m.proxy_commands(self.live, 'real-session', 'real-system')
        self.assertEqual(system[1], 'real-system')
        self.assertEqual(session[1], 'real-session')
        self.assertTrue(all(not arg.startswith(('--talk=','--own=')) for arg in system))
        self.assertTrue(all(not arg.endswith(('.Set','.Connect','.Inhibit')) for arg in system))
        self.assertEqual([arg for arg in session if arg.startswith('--own=')],
                         ['--own=dev.noctalia.Mpris','--own=dev.noctalia.Debug'])
        self.assertIn('--call=org.mpris.MediaPlayer2.*=org.mpris.MediaPlayer2.Player.PlayPause@/org/mpris/MediaPlayer2', session)
        self.assertEqual([arg for arg in session if '.Properties.Set' in arg],
                         ['--call=org.mpris.MediaPlayer2.*=org.freedesktop.DBus.Properties.Set@/org/mpris/MediaPlayer2'])

    def test_proxy_probe_accepts_request_name_denial_reply_and_rejects_success(self):
        with mock.patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],1,'','Call failed: org.freedesktop.DBus.Error.ServiceUnknown')):
            m.verify_proxy('private',session=True)
        with mock.patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'u 1\n','')):
            with self.assertRaises(m.DesktopError):m.verify_proxy('private',session=True)

    def test_main_compositor_guard_rejects_nested_socket(self):
        with (mock.patch.object(m,'run',return_value=subprocess.CompletedProcess([],0,'100\n')),
              mock.patch.object(m,'peer_pid',return_value=101)):
            with self.assertRaisesRegex(m.DesktopError,'nested'):
                m.require_session()

    def test_compositor_guard_uses_real_manager_bus_from_restricted_launcher(self):
        os.environ['DBUS_SESSION_BUS_ADDRESS']='unix:path=/restricted/session-bus'
        with (mock.patch.object(m,'run',return_value=subprocess.CompletedProcess([],0,'100\n')) as run,
              mock.patch.object(m,'peer_pid',return_value=100),mock.patch.object(m,'identity',return_value=self.niri)):
            self.assertEqual(m.require_session(), self.niri)
        self.assertNotIn('DBUS_SESSION_BUS_ADDRESS',run.call_args.kwargs['env'])
        self.assertEqual(os.environ['DBUS_SESSION_BUS_ADDRESS'],'unix:path=/restricted/session-bus')

    def test_session_start_preserves_idle_owners_and_never_starts_swaybg(self):
        with mock.patch.object(m,'require_session'), mock.patch.object(m,'run') as run:
            self.assertEqual(m.dispatch(['session-start'], self.value), 0)
        self.assertEqual(run.call_args_list[-1].args[0], ['systemctl','--user','start',m.BAR_UNIT,*m.KEEP_UNITS])
        self.assertNotIn('dotfiles-niri-wallpaper.service', str(run.call_args_list))

    def test_menu_wallpaper_and_music_routes_use_native_panels(self):
        cases = [(['applications'],('panel-toggle','launcher')), (['menu'],('panel-toggle','control-center')),
                 (['bar','menu'],('settings-open','bar')), (['wallpaper','choose'],('panel-toggle','wallpaper')),
                 (['music'],('panel-toggle','dotfiles/moonlit-music:room'))]
        for arguments, expected in cases:
            with self.subTest(arguments=arguments), mock.patch.object(m,'ipc',return_value='') as ipc:
                m.dispatch(arguments,self.value)
                ipc.assert_called_once_with(self.value,expected)

    def test_legacy_idle_and_presentation_use_pinned_file_argv(self):
        for arguments in (['idle'], ['lock'], ['presentation','toggle']):
            with mock.patch.object(m.os,'execv') as execute:
                m.dispatch(arguments,self.value)
                execute.assert_called_once_with('/usr/bin/python3',['/usr/bin/python3',str(self.legacy),*arguments])
        with self.assertRaisesRegex(m.DesktopError,'owns wallpaper'):
            m.dispatch(['wallpaper-run'], self.value)

    def test_media_argv_keeps_user_value_literal_and_requires_supported_arity(self):
        bus='org.mpris.MediaPlayer2.a;$(touch /tmp/not-run)'
        with mock.patch.object(m,'live_environment',return_value={'safe':'env'}), mock.patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],0)) as run:
            m.dispatch(['media','select',bus],self.value)
            self.assertEqual(run.call_args.args[0][-2:],['select',bus])
            self.assertFalse(run.call_args.kwargs.get('shell',False))
        for args in (['media'],['media','next','extra'],['media','seek'],['media','volume']):
            with self.assertRaises(m.DesktopError):m.dispatch(args,self.value)

    def test_gui_launch_uses_niri_environment_preserves_cwd_and_literal_argv(self):
        args=['app','a b','$(not-executed)','semicolon;literal']
        with mock.patch.object(m,'require_session'),mock.patch.object(m,'run',return_value=subprocess.CompletedProcess([],0)) as run:
            m.dispatch(['launch','--',*args], self.value)
        command=run.call_args.args[0]
        self.assertEqual(command[:5],['niri','msg','action','spawn','--'])
        self.assertEqual(command[-4:],args)
        self.assertEqual(command[8:10],['moonlit-app',os.getcwd()])
        self.assertEqual(command[7],'cd -- "$1" && shift && exec "$@"')
        self.assertNotIn('env',run.call_args.kwargs)

    def test_terminal_true_strips_only_our_prefix_and_retains_exec_quoting(self):
        original='nvim "a b.md" \'literal$HOME\''
        with mock.patch.object(m,'host_launch',return_value=0) as launch:
            m.terminal_launch(self.value,['-e','sh','-lc',m.launcher_prefix(self.value)+original])
            launch.assert_called_once_with(['kitty','-e','sh','-lc',original])
        with mock.patch.object(m,'host_launch',return_value=0) as launch:
            m.terminal_launch(self.value,['-e','sh','-lc','printf "%s" "literal"'])
            launch.assert_called_once_with(['kitty','-e','sh','-lc','printf "%s" "literal"'])

    def test_live_environment_requires_all_proxy_identities_and_matching_ipc_owner(self):
        session=self.session()
        with mock.patch.object(m,'require_session',return_value=self.niri),mock.patch.object(m,'alive',return_value=True),mock.patch.object(m,'peer_pid',return_value=session['shell']['pid']):
            self.assertEqual(m.live_environment(self.value)['DBUS_SYSTEM_BUS_ADDRESS'],session['DBUS_SYSTEM_BUS_ADDRESS'])
        with mock.patch.object(m,'require_session',return_value=self.niri),mock.patch.object(m,'alive',side_effect=lambda item:item!=session['session_proxy']):
            with self.assertRaisesRegex(m.DesktopError,'does not belong'):m.live_environment(self.value)
        with mock.patch.object(m,'require_session',return_value=self.niri),mock.patch.object(m,'alive',return_value=True),mock.patch.object(m,'peer_pid',return_value=999):
            with self.assertRaisesRegex(m.DesktopError,'another process'):m.live_environment(self.value)

    def test_status_requires_actual_ipc_json_and_reports_validated_identities(self):
        session=self.session()
        with mock.patch.object(m,'ipc',return_value='{"running":true}'),contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(m.dispatch(['status'],self.value),0)
        result=json.loads(output.getvalue())
        self.assertTrue(result['ready'])
        self.assertEqual(result['processes']['shell'],session['shell'])
        with mock.patch.object(m,'live_environment',return_value={}),mock.patch.object(m,'run',return_value=subprocess.CompletedProcess([],0,'error: not ready\n')):
            with self.assertRaisesRegex(m.DesktopError,'not ready'):m.ipc(self.value,['status'])

    def test_failed_runner_start_keeps_previous_live_session_record(self):
        old=self.session()
        (self.live/'processes.json').write_text(json.dumps(old))
        with mock.patch.object(m,'require_session',return_value=self.niri),mock.patch.object(m,'alive',return_value=True),mock.patch.object(m.subprocess,'Popen') as spawn:
            with self.assertRaisesRegex(m.DesktopError,'still alive'):m.shell(self.value)
        self.assertEqual(json.loads((self.live/'session.json').read_text()),old)
        spawn.assert_not_called()

    def test_previous_niri_identity_does_not_prevent_clean_restart(self):
        (self.live/'processes.json').write_text(json.dumps({'niri':self.niri}))
        with mock.patch.object(m,'require_session',return_value=self.niri),mock.patch.object(m,'alive',side_effect=lambda item:item==self.niri),mock.patch.object(m,'run',return_value=subprocess.CompletedProcess([],0,'b true\n')):
            with self.assertRaisesRegex(m.DesktopError,'media owner'):m.shell(self.value)


@unittest.skipUnless(os.environ.get('MOONLIT_TEST_PRIVATE_BUS')=='1','opt-in isolated D-Bus policy fixture')
class PrivateBusTests(unittest.TestCase):
    def test_proxies_block_device_writes_and_preserve_only_native_ownership(self):
        with tempfile.TemporaryDirectory(prefix='moonlit-policy-') as directory:
            root=Path(directory)
            config=root/'dbus.conf'
            config.write_text('''<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN" "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig><type>session</type><listen>unix:tmpdir=/tmp</listen><auth>EXTERNAL</auth>
<policy context="default"><allow send_destination="*" eavesdrop="true"/><allow eavesdrop="true"/><allow own="*"/></policy></busconfig>''')
            children=[]
            try:
                bus=subprocess.Popen(['dbus-daemon','--nofork','--print-address','--config-file='+str(config)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                children.append(bus)
                address=bus.stdout.readline().strip()
                self.assertTrue(address,'private daemon could not start')
                for index,command in enumerate(m.proxy_commands(root,address,address)):
                    proxy=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    children.append(proxy)
                    path=root/('system-bus' if index==0 else 'session-bus')
                    deadline=time.monotonic()+3
                    while not path.exists() and proxy.poll() is None and time.monotonic()<deadline:time.sleep(.025)
                    self.assertTrue(path.exists())
                    proxy_address='unix:path='+str(path)
                    m.verify_proxy(proxy_address,session=index==1)
                    if index==1:
                        for name in ('dev.noctalia.Mpris','org.freedesktop.Notifications','org.freedesktop.ScreenSaver','org.kde.StatusNotifierWatcher'):
                            reply=subprocess.run(['busctl','--address='+proxy_address,'call','org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','RequestName','su',name,'4'],capture_output=True,text=True,timeout=4)
                            if name=='dev.noctalia.Mpris':self.assertEqual((reply.returncode,reply.stdout.strip()),(0,'u 1'),reply.stderr)
                            else:
                                self.assertNotEqual(reply.returncode,0,reply.stdout)
                                self.assertTrue(any(word in reply.stderr.lower() for word in ('denied','serviceunknown')),reply.stderr)
                        self.check_media_transport(address,proxy_address,children)
                self.check_device_capabilities(root,address,children)
            finally:
                for child in reversed(children):
                    m.stop_process(child)
                    if child.stdout:child.stdout.close()
                    if child.stderr:child.stderr.close()

    def check_device_capabilities(self,root,address,children):
        # Distinct service connections are essential: real NM and BlueZ each
        # have their own unique bus owner. No host service is contacted.
        provider='''import sys
from gi.repository import Gio,GLib
connection=Gio.DBusConnection.new_for_address_sync(sys.argv[1],Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT|Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,None,None)
connection.call_sync('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','RequestName',GLib.Variant('(su)',(sys.argv[2],4)),None,Gio.DBusCallFlags.NONE,2000,None)
xml='<node><interface name="test.MoonlitDevice"><method name="Change"><arg name="result" type="s" direction="out"/></method></interface></node>'
def method(conn,sender,path,interface,name,args,invocation):invocation.return_value(GLib.Variant('(s)',('fixture accepted',)))
connection.register_object('/test/device',Gio.DBusNodeInfo.new_for_xml(xml).interfaces[0],method,None,None)
print('ready',flush=True)
GLib.MainLoop().run()
'''
        import select
        for name in ('org.freedesktop.NetworkManager','org.bluez'):
            proc=subprocess.Popen([sys.executable,'-c',provider,address,name],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            children.append(proc)
            self.assertTrue(select.select([proc.stdout],[],[],4)[0],'device fixture did not start')
            self.assertEqual(proc.stdout.readline().strip(),'ready')
        for index,selected in enumerate(([],['audio'],['network'],['bluetooth'],['audio','network','bluetooth'])):
            profile=root/('capabilities-'+str(index));profile.mkdir()
            command=m.proxy_commands(profile,address,address,selected)[0]
            proxy=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);children.append(proxy)
            path=profile/'system-bus';deadline=time.monotonic()+3
            while not path.exists() and proxy.poll() is None and time.monotonic()<deadline:time.sleep(.025)
            self.assertTrue(path.exists())
            proxy_address='unix:path='+str(path)
            m.verify_proxy(proxy_address)
            for capability,name in (('network','org.freedesktop.NetworkManager'),('bluetooth','org.bluez')):
                reply=subprocess.run(['busctl','--address='+proxy_address,'call',name,'/test/device','test.MoonlitDevice','Change'],capture_output=True,text=True,timeout=4)
                with self.subTest(capabilities=selected,service=name):
                    if capability in selected:
                        self.assertEqual(reply.returncode,0,reply.stderr)
                        self.assertIn('fixture accepted',reply.stdout)
                    else:
                        self.assertNotEqual(reply.returncode,0)
                        self.assertIn('denied',reply.stderr.lower())
            m.stop_process(proxy)

    def check_media_transport(self, address, proxy_address, children):
        # These processes are synthetic protocol fixtures on the private bus;
        # no real player, audio device or host session is reached.
        import gi
        gi.require_version('Gio','2.0')
        from gi.repository import Gio, GLib
        provider = '''import sys
from gi.repository import Gio,GLib
address,name,path=sys.argv[1:]
connection=Gio.DBusConnection.new_for_address_sync(address,Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT|Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,None,None)
connection.call_sync('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','RequestName',GLib.Variant('(su)',(name,4)),None,Gio.DBusCallFlags.NONE,2000,None)
xml='<node><interface name="org.mpris.MediaPlayer2.Player"><property name="PlaybackStatus" type="s" access="read"/><property name="Shuffle" type="b" access="readwrite"/><method name="PlayPause"/></interface><interface name="dev.noctalia.Mpris"><method name="Read"><arg name="value" type="s" direction="out"/></method><signal name="Changed"><arg name="value" type="s"/></signal></interface></node>'
state={'PlaybackStatus':GLib.Variant('s','Paused'),'Shuffle':GLib.Variant('b',False)}
def method(conn,sender,path,interface,name,args,invocation):
 if name=='Read':
  invocation.return_value(GLib.Variant('(s)',('fixture ready',)))
  connection.emit_signal(None,path,'dev.noctalia.Mpris','Changed',GLib.Variant('(s)',('fixture changed',)))
 else:
  state['PlaybackStatus']=GLib.Variant('s','Playing')
  connection.emit_signal(None,path,'org.freedesktop.DBus.Properties','PropertiesChanged',GLib.Variant('(sa{sv}as)',('org.mpris.MediaPlayer2.Player',{'PlaybackStatus':state['PlaybackStatus']},[])))
  invocation.return_value(None)
def get(conn,sender,path,interface,name):return state[name]
def put(conn,sender,path,interface,name,value):state[name]=value;return True
for interface in Gio.DBusNodeInfo.new_for_xml(xml).interfaces:connection.register_object(path,interface,method,get,put)
print('ready',flush=True)
GLib.MainLoop().run()
'''
        for bus,name,path in ((address,'org.mpris.MediaPlayer2.moonlit_test','/org/mpris/MediaPlayer2'),
                              (proxy_address,'dev.noctalia.Mpris','/dev/noctalia/Mpris')):
            proc=subprocess.Popen([sys.executable,'-c',provider,bus,name,path],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            children.append(proc)
            # Bounded wait also makes a fixture startup failure inspectable.
            import select
            self.assertTrue(select.select([proc.stdout],[],[],4)[0],'provider did not start')
            self.assertEqual(proc.stdout.readline().strip(),'ready')
        events=[]
        client=Gio.DBusConnection.new_for_address_sync(proxy_address,Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT|Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,None,None)
        for sender,interface,signal_name,path in (
                ('dev.noctalia.Mpris','dev.noctalia.Mpris','Changed','/dev/noctalia/Mpris'),
                ('org.mpris.MediaPlayer2.moonlit_test','org.freedesktop.DBus.Properties','PropertiesChanged','/org/mpris/MediaPlayer2'),
                ('org.freedesktop.DBus','org.freedesktop.DBus','NameOwnerChanged','/org/freedesktop/DBus')):
            client.signal_subscribe(sender,interface,signal_name,path,None,Gio.DBusSignalFlags.NONE,
                lambda _c,_s,_p,_i,name,args,*_u:events.append((name,args.unpack())))
        client.flush_sync(None)
        def call(name,path,interface,method,signature=None,*arguments):
            command=['busctl','--address='+proxy_address,'call',name,path,interface,method]
            if signature:command += [signature,*arguments]
            return subprocess.run(command,capture_output=True,text=True,timeout=4)
        player='org.mpris.MediaPlayer2.moonlit_test';path='/org/mpris/MediaPlayer2';props='org.freedesktop.DBus.Properties'
        reply=call(player,path,props,'GetAll','s','org.mpris.MediaPlayer2.Player')
        self.assertEqual(reply.returncode,0,reply.stderr)
        self.assertIn('Paused',reply.stdout)
        reply=call(player,path,props,'Set','ssv','org.mpris.MediaPlayer2.Player','Shuffle','b','true')
        self.assertEqual(reply.returncode,0,reply.stderr)
        reply=call(player,path,props,'Get','ss','org.mpris.MediaPlayer2.Player','Shuffle')
        self.assertIn('true',reply.stdout)
        self.assertNotEqual(call(player,'/outside',props,'Set','ssv','org.mpris.MediaPlayer2.Player','Shuffle','b','false').returncode,0)
        self.assertEqual(call(player,path,'org.mpris.MediaPlayer2.Player','PlayPause').returncode,0)
        reply=call('dev.noctalia.Mpris','/dev/noctalia/Mpris','dev.noctalia.Mpris','Read')
        self.assertEqual(reply.returncode,0,reply.stderr)
        self.assertIn('fixture ready',reply.stdout)
        m.stop_process(children[-2])  # Exactly the fixture's raw MPRIS owner.
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            while GLib.MainContext.default().pending():GLib.MainContext.default().iteration(False)
            if {'Changed','PropertiesChanged','NameOwnerChanged'} <= {item[0] for item in events}:break
            time.sleep(.025)
        client.close_sync(None)
        self.assertIn(('Changed',('fixture changed',)),events)
        self.assertTrue(any(name=='PropertiesChanged' and data[1].get('PlaybackStatus')=='Playing' for name,data in events),events)
        self.assertTrue(any(name=='NameOwnerChanged' and data[0]==player and not data[2] for name,data in events),events)


if __name__=='__main__':unittest.main()
