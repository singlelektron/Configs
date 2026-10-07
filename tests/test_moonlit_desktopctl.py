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

    def test_session_actions_require_the_capability_and_keep_native_confirmation(self):
        with mock.patch.object(m, 'host_launch', return_value=0) as launch:
            with self.assertRaisesRegex(m.DesktopError, 'not been enabled'):
                m.dispatch(['session-action', 'shutdown'], self.value)
            launch.assert_not_called()
            self.value['capabilities'] = ['session']
            m.dispatch(['session-action', 'logout'], self.value)
            self.assertEqual(launch.call_args.args[0], ['niri', 'msg', 'action', 'quit'])
            with self.assertRaisesRegex(m.DesktopError, 'Unknown session'):
                m.dispatch(['session-action', 'force-reboot'], self.value)
            self.assertEqual(m.proxy_commands(self.live, 'session', 'system', ['session']),
                             m.proxy_commands(self.live, 'session', 'system'))

    def test_actual_suspend_command_never_suspends_after_a_failed_lock(self):
        self.value['capabilities'] = ['session']
        with mock.patch.object(m, 'host_launch', return_value=0) as launch:
            m.dispatch(['session-action', 'suspend'], self.value)
            command = launch.call_args.args[0]
        fake = self.root/'systemctl'
        fake.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$MOONLIT_COMMAND_LOG"\n'
                        'if [ "$1" = --user ]; then exit "$MOONLIT_LOCK_RESULT"; fi\n')
        fake.chmod(0o700)
        log = self.root/'commands'
        for lock_result in ('3', '0'):
            log.unlink(missing_ok=True)
            result = subprocess.run(command, env=dict(os.environ, PATH=str(self.root),
                MOONLIT_COMMAND_LOG=str(log), MOONLIT_LOCK_RESULT=lock_result),
                capture_output=True, text=True, timeout=5)
            expected = ['--user start dotfiles-niri-lock.service']
            if lock_result == '0': expected.append('suspend')
            self.assertEqual(log.read_text().splitlines(), expected)
            self.assertEqual(result.returncode, int(lock_result))

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
        for selected in (['audio'], ['network','bluetooth'], ['audio','bluetooth','network'], ['notifications'], ['caffeine'], ['session']):
            self.value['capabilities']=selected
            self.write_manifest()
            self.assertEqual(m.capabilities(m.read_manifest(self.link)), frozenset(selected))
        for selected in ('audio', None, ['unrestricted'], ['audio','audio'], [1], [{}]):
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

    def prepare_calendar(self):
        calendar=self.live/'data/noctalia/calendar-vdir'
        calendar.mkdir(parents=True,mode=0o700)
        self.value.update(capabilities=['calendar'],calendar_dir=str(calendar))
        self.write_manifest()
        return calendar

    def test_calendar_requires_private_managed_vdir_without_opening_shell_bus(self):
        calendar=self.prepare_calendar()
        self.assertEqual(m.read_manifest(self.link)['calendar_dir'],str(calendar))
        self.assertEqual(m.proxy_commands(self.live,'session','system',['calendar']),
                         m.proxy_commands(self.live,'session','system'))
        calendar.chmod(0o755)
        with self.assertRaisesRegex(m.DesktopError,'private live vdir'):m.read_manifest(self.link)
        calendar.chmod(0o700)
        self.value['calendar_dir']=str(self.root/'elsewhere');self.write_manifest()
        with self.assertRaisesRegex(m.DesktopError,'private live vdir'):m.read_manifest(self.link)

    def test_calendar_readiness_requires_current_owned_worker_and_initial_view_completion(self):
        calendar=self.prepare_calendar();session=self.session()
        session['calendar_bridge']={'pid':900,'start':901,'state':'S'}
        with mock.patch.object(m,'alive',return_value=True):
            self.assertFalse(m.calendar_status(self.value,session)['ready'])
            (calendar/'status.json').write_text(json.dumps({'ready':True,'source_count':2,'component_count':5,'error_count':1,'degraded':True}))
            state=m.calendar_status(self.value,session)
            self.assertTrue(state['ready']);self.assertTrue(state['degraded'])
            self.assertEqual(state['component_count'],5)
        with mock.patch.object(m,'alive',return_value=False):
            state=m.calendar_status(self.value,session)
            self.assertFalse(state['ready']);self.assertIn('restart',state['reason'])

    def test_calendar_loading_is_not_reported_as_ready_desktop_acceptance(self):
        self.prepare_calendar();self.session()
        for ready in (False,True):
            with (mock.patch.object(m,'ipc',return_value='{"running":true}'),
                  mock.patch.object(m,'calendar_status',return_value={'running':True,'ready':ready}),
                  contextlib.redirect_stdout(io.StringIO()) as output):
                self.assertEqual(m.dispatch(['status'],self.value),0)
            self.assertEqual(json.loads(output.getvalue())['ready'],ready)

    def test_calendar_failure_keeps_shell_and_cleanup_signals_only_owned_processes(self):
        calendar=self.prepare_calendar()
        (calendar/'status.json').write_text('{"ready":true}')
        children=[];starts=[];closed=[]
        class Child:
            def __init__(self,pid,code=0):self.pid=pid;self.returncode=None;self.code=code;self.terminated=False
            def poll(self):return self.returncode
            def wait(self,timeout=None):self.returncode=self.code;return self.code
            def terminate(self):self.terminated=True;self.returncode=0
        def spawn(argv,**kwargs):
            child=Child(1001+len(children),1 if '--output' in argv else 0)
            children.append(child);starts.append((argv,kwargs))
            if argv[0]=='xdg-dbus-proxy':Path(argv[2]).touch()
            return child
        real_close=os.close
        def close(fd):
            if fd>=1000000:closed.append(fd)
            else:real_close(fd)
        with (mock.patch.object(m,'require_session',return_value=self.niri),
              mock.patch.object(m,'run',return_value=subprocess.CompletedProcess([],0,'b false\n')),
              mock.patch.object(m,'identity',side_effect=lambda pid:dict(pid=pid,start=pid,state='S')),
              mock.patch.object(m,'verify_proxy'),mock.patch.object(m.subprocess,'Popen',side_effect=spawn),
              mock.patch.object(m,'stop_process',wraps=m.stop_process) as stop,
              mock.patch.object(m.os,'pidfd_open',side_effect=lambda pid:1000000+pid),
              mock.patch.object(m.os,'close',side_effect=close),
              mock.patch.object(m.select,'select',side_effect=[([1001003],[],[]),([1001004],[],[])]) as select_call,
              contextlib.redirect_stderr(io.StringIO()) as error):
            self.assertEqual(m.shell(self.value),0)
        self.assertEqual(select_call.call_count,2)
        self.assertIn('shell remains running',error.getvalue())
        self.assertFalse((calendar/'status.json').exists(),'stale calendar readiness must not survive restart')
        self.assertEqual(starts[2][0],m.calendar_command(self.value))
        self.assertEqual(starts[2][1]['env']['DBUS_SESSION_BUS_ADDRESS'],'unix:path=/real/session-bus')
        self.assertEqual(starts[2][1]['env']['XDG_CONFIG_HOME'],'/home/test/.config')
        self.assertEqual(starts[3][1]['env']['DBUS_SESSION_BUS_ADDRESS'],'unix:path='+str(self.live/'session-bus'))
        self.assertFalse(children[2].terminated,'already-exited bridge was only reaped')
        self.assertTrue(children[0].terminated and children[1].terminated)
        self.assertEqual([call.args[0] for call in stop.call_args_list],list(reversed(children)))
        self.assertEqual(set(closed),{1001001,1001002,1001003,1001004})
        self.assertFalse((self.live/'session.json').exists())
        self.assertEqual(json.loads((self.live/'processes.json').read_text())['calendar_bridge']['pid'],1003)

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


    def test_notifications_capability_only_grants_its_bus_name(self):
        plain=m.proxy_commands(self.live,'session','system')
        system,session=m.proxy_commands(self.live,'session','system',['notifications'])
        self.assertEqual(system,plain[0])
        self.assertEqual(set(session)-set(plain[1]),{'--own=org.freedesktop.Notifications'})
        self.assertNotIn('--own=org.freedesktop.ScreenSaver',session)

    def test_owned_notification_mask_is_idempotent_and_cleanup_needs_no_session(self):
        self.value['capabilities']=['notifications']
        with (mock.patch.object(m,'run',return_value=subprocess.CompletedProcess([],0,'masked\n')) as run,
              mock.patch.object(m,'require_session',side_effect=AssertionError('cleanup queried Niri'))):
            m.notifications_mask(self.value)
            marker,target=m.notification_mask_paths(self.value)
            inode=target.lstat().st_ino
            self.assertEqual(os.readlink(target),'/dev/null')
            m.notifications_mask(self.value)
            self.assertEqual(target.lstat().st_ino,inode)
            m.dispatch(['notifications-cleanup'],self.value)
            m.dispatch(['notifications-cleanup'],self.value)
        self.assertFalse(marker.exists());self.assertFalse(target.is_symlink())
        self.assertTrue(all('DBUS_SESSION_BUS_ADDRESS' not in item.kwargs['env'] for item in run.call_args_list))

    def test_preexisting_and_replaced_masks_are_never_unmasked(self):
        self.value['capabilities']=['notifications']
        marker,target=m.notification_mask_paths(self.value)
        target.parent.mkdir(parents=True);target.symlink_to('/dev/null')
        with mock.patch.object(m,'run',return_value=subprocess.CompletedProcess([],0,'masked\n')):
            m.notifications_mask(self.value);m.notifications_cleanup(self.value)
            self.assertTrue(target.is_symlink())
            target.unlink();m.notifications_mask(self.value)
            # Keep the owned inode alive so replacement cannot reuse it.
            old=target.parent/'old-mask';target.rename(old);target.symlink_to('/dev/null')
            m.notifications_cleanup(self.value)
            self.assertTrue(target.is_symlink());self.assertTrue(old.is_symlink())
        self.assertFalse(marker.exists())

    def test_mask_refuses_unknown_unit_and_recovers_interrupted_publication(self):
        self.value['capabilities']=['notifications']
        marker,target=m.notification_mask_paths(self.value)
        target.parent.mkdir(parents=True);target.write_text('unrelated unit')
        with mock.patch.object(m,'run') as run:
            with self.assertRaisesRegex(m.DesktopError,'existing runtime'):m.notifications_mask(self.value)
            run.assert_not_called()
        self.assertEqual(target.read_text(),'unrelated unit');target.unlink()
        with mock.patch.object(m.os,'link',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):m.notifications_mask(self.value)
        candidate=Path(json.loads(marker.read_text())['candidate'])
        self.assertTrue(candidate.is_symlink())
        with mock.patch.object(m,'run'):
            m.notifications_cleanup(self.value)
        self.assertFalse(candidate.is_symlink());self.assertFalse(marker.exists())

    def test_shadowed_runtime_mask_fails_before_daemon_takeover(self):
        self.value['capabilities']=['notifications']
        with mock.patch.object(m,'run',return_value=subprocess.CompletedProcess([],0,'loaded\n')):
            with self.assertRaisesRegex(m.DesktopError,'shadowed'):m.notifications_mask(self.value)
        marker,target=m.notification_mask_paths(self.value)
        self.assertFalse(marker.exists());self.assertFalse(target.is_symlink())

    def test_notification_prepare_archives_private_raw_json_and_preserves_native_dnd(self):
        self.value['capabilities']=['notifications']
        state=self.live/'notification-state.json';state.write_text('{"dnd":true}')
        calls=[]
        def run(argv,**kwargs):
            calls.append((argv,kwargs))
            if argv[:2]==['makoctl','mode']:answer='default\n'
            elif argv[0]=='makoctl':answer='{"synthetic": ["preserve exact fixture"]}\n'
            elif '--property=MainPID' in argv:answer='101\n' if m.MAKO_UNITS[0] in argv else '0\n'
            else:answer=''
            return subprocess.CompletedProcess(argv,0,answer)
        with (mock.patch.object(m,'require_session'),mock.patch.object(m,'notifications_mask'),
              mock.patch.object(m,'live_environment',side_effect=FileNotFoundError),
              mock.patch.object(m,'notification_owner',side_effect=[{'name':':1.2','pid':101},None]),
              mock.patch.object(m,'run',side_effect=run)):
            m.notifications_prepare(self.value)
        archive=list((self.live/'notification-archive').iterdir())[0]
        self.assertEqual(archive.stat().st_mode & 0o777,0o700)
        for name in ('list.json','history.json','mode.txt'):
            self.assertEqual((archive/name).stat().st_mode & 0o777,0o600)
        self.assertEqual((archive/'history.json').read_text(),'{"synthetic": ["preserve exact fixture"]}\n')
        self.assertTrue(json.loads(state.read_text())['dnd'],'fallback mako must not replace the latest native DND')
        self.assertEqual([argv for argv,_ in calls if 'stop' in argv],
                         [['systemctl','--user','stop',m.MAKO_UNITS[0]]])
        state.unlink()
        with (mock.patch.object(m,'require_session'),mock.patch.object(m,'notifications_mask'),
              mock.patch.object(m,'live_environment',side_effect=FileNotFoundError),
              mock.patch.object(m,'notification_owner',side_effect=[{'name':':1.2','pid':101},None]),
              mock.patch.object(m,'run',side_effect=run)):
            m.notifications_prepare(self.value)
        self.assertFalse(json.loads(state.read_text())['dnd'])

    def test_notification_prepare_unknown_owner_refuses_without_stopping_it(self):
        self.value['capabilities']=['notifications']
        with (mock.patch.object(m,'require_session'),mock.patch.object(m,'notifications_mask'),
              mock.patch.object(m,'live_environment',side_effect=FileNotFoundError),
              mock.patch.object(m,'notification_owner',return_value={'name':':1.2','pid':900}),
              mock.patch.object(m,'run',return_value=subprocess.CompletedProcess([],0,'101\n')) as run,
              mock.patch.object(m,'notifications_cleanup') as cleanup):
            with self.assertRaisesRegex(m.DesktopError,'Another notification'):m.notifications_prepare(self.value)
            cleanup.assert_called_once_with(self.value)
        self.assertFalse(any('stop' in item.args[0] for item in run.call_args_list))
        self.assertFalse((self.live/'notification-archive').exists())

    def test_repeated_start_accepts_only_validated_same_release_owner(self):
        self.value['capabilities']=['notifications'];self.session()
        with (mock.patch.object(m,'require_session'),mock.patch.object(m,'live_environment') as live,
              mock.patch.object(m,'notification_status',return_value={'ready':True}),
              mock.patch.object(m,'notifications_mask') as mask,mock.patch.object(m,'notification_owner') as owner):
            m.notifications_prepare(self.value)
            live.assert_called_once_with(self.value);mask.assert_called_once_with(self.value)
            owner.assert_not_called()
        with (mock.patch.object(m,'require_session'),mock.patch.object(m,'notifications_prepare'),
              mock.patch.object(m,'run') as run):
            m.dispatch(['session-start'],self.value)
        self.assertNotIn(m.MAKO_UNITS[0],run.call_args_list[-1].args[0])
        self.assertIn('dotfiles-niri-idle.service',run.call_args_list[-1].args[0])

    def test_notification_readiness_checks_proxy_owner_and_actual_server(self):
        self.value['capabilities']=['notifications'];session=self.session()
        with (mock.patch.object(m,'notification_owner',return_value={'name':':1.2','pid':session['shell']['pid']}),
              mock.patch.object(m,'run') as run):
            self.assertFalse(m.notification_status(self.value,session)['ready']);run.assert_not_called()
        with mock.patch.object(m,'notification_owner',return_value={'name':':1.2','pid':session['session_proxy']['pid']}):
            for answer,ready in [('ssss "noctalia" "noctalia-dev" "5.2.1" "1.2"',True),
                                 ('ssss "other" "vendor" "1" "1.2"',False)]:
                with mock.patch.object(m,'run',return_value=subprocess.CompletedProcess([],0,answer)) as run:
                    self.assertEqual(m.notification_status(self.value,session)['ready'],ready)
                    self.assertIn('--auto-start=no',run.call_args.args[0]);self.assertIn(':1.2',run.call_args.args[0])

    def test_notification_toggle_persists_native_dnd_and_restore_waits_for_known_mako(self):
        self.value['capabilities']=['notifications']
        with mock.patch.object(m,'ipc',side_effect=['','on\n']) as ipc:
            m.dispatch(['notifications','toggle'],self.value)
        self.assertTrue(json.loads((self.live/'notification-state.json').read_text())['dnd'])
        with (mock.patch.object(m,'require_session'),
              mock.patch.object(m,'notification_owner',side_effect=[None,{'name':':1.8','pid':101}]),
              mock.patch.object(m,'run',return_value=subprocess.CompletedProcess([],0,'101\n')) as run,
              mock.patch.object(m.time,'sleep') as sleep):
            m.restore_mako_dnd(self.value)
        sleep.assert_called_once_with(.05)
        self.assertEqual(run.call_args.args[0],['makoctl','mode','-a','do-not-disturb'])


    def presentation_run(self,argv,**kwargs):
        answer='active\n' if '--property=ActiveState' in argv else '100\n'
        return subprocess.CompletedProcess(argv,0,answer)

    def test_presentation_on_off_and_cleanup_restore_only_existing_idle_owner(self):
        self.value['capabilities']=['caffeine']
        flag=self.root/'dotfiles-niri/presentation'
        with (mock.patch.object(m,'require_session',return_value=self.niri),
              mock.patch.object(m,'alive',return_value=True),mock.patch.object(m,'ipc') as ipc,
              mock.patch.object(m,'run',side_effect=self.presentation_run) as run):
            m.dispatch(['presentation','on'],self.value)
            inode=flag.stat().st_ino
            m.dispatch(['presentation','on'],self.value)
            self.assertEqual(flag.stat().st_ino,inode)
            m.dispatch(['presentation','off'],self.value)
            m.dispatch(['presentation-cleanup'],self.value)
        self.assertFalse(flag.exists());self.assertFalse((self.live/'presentation-owner.json').exists())
        self.assertEqual([item.args[0] for item in run.call_args_list if 'stop' in item.args[0]],
                         [['systemctl','--user','stop','dotfiles-niri-idle.service']])
        self.assertEqual([item.args[0] for item in run.call_args_list if 'start' in item.args[0]],
                         [['systemctl','--user','start','dotfiles-niri-idle.service']])
        self.assertFalse(any('session-events' in str(item) or 'lock.service' in str(item) for item in run.call_args_list))
        self.assertTrue(all('DBUS_SESSION_BUS_ADDRESS' not in item.kwargs['env'] for item in run.call_args_list))
        ipc.assert_called_with(self.value,['plugin','dotfiles/moonlit-controls:awake','all','refresh'])

    def test_presentation_initially_inactive_refuses_before_mutation_and_preserves_external_flag(self):
        self.value['capabilities']=['caffeine']
        flag=self.root/'dotfiles-niri/presentation'
        with (mock.patch.object(m,'require_session',return_value=self.niri),
              mock.patch.object(m,'run',return_value=subprocess.CompletedProcess([],0,'inactive\n')) as run):
            with self.assertRaisesRegex(m.DesktopError,'idle service to be active'):
                m.presentation(self.value,'on')
        self.assertFalse(flag.exists());self.assertFalse(any('stop' in item.args[0] for item in run.call_args_list))
        flag.write_text('on\n')
        with mock.patch.object(m,'require_session',side_effect=AssertionError('cleanup queried session')):
            m.presentation_cleanup(self.value)
        self.assertTrue(flag.exists())
        with (mock.patch.object(m,'require_session',return_value=self.niri),mock.patch.object(m,'ipc'),
              mock.patch.object(m,'run',side_effect=self.presentation_run) as run):
            m.presentation(self.value,'off')
        self.assertEqual(run.call_args.args[0],['/usr/bin/python3',str(self.legacy),'presentation','off'])

    def test_presentation_cleanup_replaced_inode_does_not_restart_idle_or_remove_new_flag(self):
        self.value['capabilities']=['caffeine'];flag=self.root/'dotfiles-niri/presentation'
        with (mock.patch.object(m,'require_session',return_value=self.niri),mock.patch.object(m,'ipc'),
              mock.patch.object(m,'run',side_effect=self.presentation_run)):
            m.presentation(self.value,'on')
        flag.rename(flag.with_name('previous-owned'));flag.write_text('external')
        with mock.patch.object(m,'alive',return_value=True),mock.patch.object(m,'run') as run:
            m.presentation_cleanup(self.value)
        run.assert_not_called();self.assertEqual(flag.read_text(),'external')
        self.assertFalse((self.live/'presentation-owner.json').exists())

    def test_presentation_cleanup_after_session_ended_only_removes_own_flag(self):
        self.value['capabilities']=['caffeine'];flag=self.root/'dotfiles-niri/presentation'
        with (mock.patch.object(m,'require_session',return_value=self.niri),mock.patch.object(m,'ipc'),
              mock.patch.object(m,'run',side_effect=self.presentation_run)):
            m.presentation(self.value,'toggle')
        with (mock.patch.object(m,'require_session',side_effect=AssertionError('no live session')),
              mock.patch.object(m,'alive',return_value=False),mock.patch.object(m,'run') as run):
            m.dispatch(['presentation-cleanup'],self.value)
            m.dispatch(['presentation-cleanup'],self.value)
        self.assertFalse(flag.exists());run.assert_not_called()

    def test_presentation_failed_publication_restores_idle_and_removes_reserved_inode(self):
        self.value['capabilities']=['caffeine']
        with (mock.patch.object(m,'require_session',return_value=self.niri),mock.patch.object(m,'alive',return_value=True),
              mock.patch.object(m,'run',side_effect=self.presentation_run) as run,
              mock.patch.object(m.os,'link',side_effect=OSError('synthetic publication failure'))):
            with self.assertRaisesRegex(OSError,'publication failure'):m.presentation(self.value,'on')
        self.assertIn(['systemctl','--user','start','dotfiles-niri-idle.service'],[item.args[0] for item in run.call_args_list])
        self.assertFalse((self.live/'presentation-owner.json').exists())
        self.assertFalse(list((self.root/'dotfiles-niri').glob('.moonlit-presentation-*')))

    def test_presentation_interrupted_stop_recovers_pending_record_and_ipc_failure_is_nonfatal(self):
        self.value['capabilities']=['caffeine'];flag=self.root/'dotfiles-niri/presentation'
        with (mock.patch.object(m,'require_session',return_value=self.niri),
              mock.patch.object(m,'run',side_effect=self.presentation_run),
              mock.patch.object(m,'release_presentation',side_effect=[None,KeyboardInterrupt]),
              mock.patch.object(m.os,'link',side_effect=KeyboardInterrupt)):
            with self.assertRaises(KeyboardInterrupt):m.presentation(self.value,'on')
        self.assertFalse(flag.exists());self.assertTrue((self.live/'presentation-owner.json').exists())
        with mock.patch.object(m,'alive',return_value=True),mock.patch.object(m,'run',side_effect=self.presentation_run) as run:
            m.presentation_cleanup(self.value)
        self.assertIn(['systemctl','--user','start','dotfiles-niri-idle.service'],[item.args[0] for item in run.call_args_list])
        with (mock.patch.object(m,'require_session',return_value=self.niri),
              mock.patch.object(m,'run',side_effect=self.presentation_run),
              mock.patch.object(m,'ipc',side_effect=m.DesktopError('not running'))):
            self.assertEqual(m.presentation(self.value,'on'),0)
        self.assertTrue(flag.exists())

    def test_repeated_session_start_preserves_active_presentation(self):
        self.value['capabilities']=['caffeine'];flag=self.root/'dotfiles-niri/presentation'
        flag.parent.mkdir();flag.write_text('on\n')
        with (mock.patch.object(m,'require_session'),mock.patch.object(m,'live_environment'),mock.patch.object(m,'run') as run):
            m.dispatch(['session-start'],self.value)
        self.assertNotIn('dotfiles-niri-idle.service',run.call_args.args[0])
        self.assertIn('dotfiles-niri-session-events.service',run.call_args.args[0])


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
                self.check_notification_capability(root,address,children)
            finally:
                for child in reversed(children):
                    m.stop_process(child)
                    if child.stdout:child.stdout.close()
                    if child.stderr:child.stderr.close()

    def check_notification_capability(self,root,address,children):
        profile=root/'notifications';profile.mkdir()
        command=m.proxy_commands(profile,address,address,['notifications'])[1]
        proxy=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);children.append(proxy)
        path=profile/'session-bus';deadline=time.monotonic()+3
        while not path.exists() and proxy.poll() is None and time.monotonic()<deadline:time.sleep(.025)
        self.assertTrue(path.exists())
        provider='''import sys
from gi.repository import Gio,GLib
connection=Gio.DBusConnection.new_for_address_sync(sys.argv[1],Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT|Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,None,None)
reply=connection.call_sync('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','RequestName',GLib.Variant('(su)',('org.freedesktop.Notifications',4)),None,Gio.DBusCallFlags.NONE,2000,None)
assert reply.unpack()==(1,),reply
xml='<node><interface name="org.freedesktop.Notifications"><method name="GetServerInformation"><arg type="s" direction="out"/><arg type="s" direction="out"/><arg type="s" direction="out"/><arg type="s" direction="out"/></method></interface></node>'
def method(conn,sender,path,interface,name,args,invocation):invocation.return_value(GLib.Variant('(ssss)',('noctalia','noctalia-dev','5.2.1','1.2')))
connection.register_object('/org/freedesktop/Notifications',Gio.DBusNodeInfo.new_for_xml(xml).interfaces[0],method,None,None)
print('ready',flush=True)
GLib.MainLoop().run()
'''
        proc=subprocess.Popen([sys.executable,'-c',provider,'unix:path='+str(path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        children.append(proc)
        import select
        self.assertTrue(select.select([proc.stdout],[],[],4)[0],'notification fixture did not start')
        self.assertEqual(proc.stdout.readline().strip(),'ready')
        owner=m.notification_owner(address)
        self.assertEqual(owner['pid'],proxy.pid,'host bus sees the authenticated proxy, not its provider')
        self.assertNotEqual(owner['pid'],proc.pid)
        bus_path=address.split('unix:path=',1)[1].split(',',1)[0]
        (root/'bus').symlink_to(bus_path)
        with mock.patch.dict(os.environ,{'XDG_RUNTIME_DIR':str(root)}):
            state=m.notification_status({'capabilities':['notifications']},{'session_proxy':{'pid':proxy.pid}})
        self.assertTrue(state['ready'],state)
        reply=subprocess.run(['busctl','--address=unix:path='+str(path),'call','org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','RequestName','su','org.freedesktop.ScreenSaver','4'],capture_output=True,text=True,timeout=4)
        self.assertNotEqual(reply.returncode,0,'notifications must not grant screen lock ownership')
        m.stop_process(proc)
        deadline=time.monotonic()+3
        while m.notification_owner(address) and time.monotonic()<deadline:time.sleep(.025)
        self.assertIsNone(m.notification_owner(address))

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
