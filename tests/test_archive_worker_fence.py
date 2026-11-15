"""Production Java-fence races and Android integration order, without app build."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
JAVA=ROOT/'android/app/src/main/java/com/tagundo/elichika'

class ArchiveWorkerFenceTests(unittest.TestCase):
    def test_production_fence_executes_real_thread_and_ownership_races(self):
        compiler=([shutil.which('javac')] if shutil.which('javac') else
                  ['java','-Xmx96m','com.sun.tools.javac.Main'])
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(compiler+['-source','8','-target','8','-d',directory,str(JAVA/'ArchiveWorkerFence.java'),str(ROOT/'tests/ArchiveWorkerFenceRaceTest.java')],check=True,capture_output=True,text=True,timeout=30)
            result=subprocess.run(['java','-Xmx64m','-ea','-cp',directory,'com.tagundo.elichika.ArchiveWorkerFenceRaceTest'],check=True,capture_output=True,text=True,timeout=15)
        summary=json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(summary,{'status':'PASS','production_fence_race_cases':8})
        print(result.stdout,end='')

    def test_preparation_waits_off_main_and_rechecks_owner_before_writes(self):
        source=(JAVA/'ServerService.kt').read_text()
        prep=source.split('val appContext = applicationContext',1)[1].split('} catch (error: PayloadUpgrade.CostumeRecoveryRequired)',1)[0]
        self.assertLess(prep.index('Thread({'),prep.index('archiveWorkers.awaitIdle()'))
        self.assertLess(prep.index('archiveWorkers.awaitIdle()'),prep.index('if (destroyed || current !== this) return@Thread'))
        self.assertLess(prep.index('if (destroyed || current !== this) return@Thread'),prep.index('AssetInstaller.install'))
        self.assertLess(prep.index('archiveWorkers.awaitIdle()'),prep.index('PyServers.ensureStarted'))
        self.assertIn('private val archiveWorkers = ArchiveWorkerFence()',source.split('companion object {',1)[1])
        for name,end in [('startServer','private fun awaitServerReadiness'),('reserveForInstall','internal fun pauseReservedInstall')]:
            fn=source.split('fun '+name+'(',1)[1].split(end,1)[0]
            self.assertIn('check(!archiveWorkers.isBusy())',fn)
        dispatch=source.split('private fun dispatchCommand',1)[1].split('when (intent.action)',1)[0]
        for action in ['ACTION_START','ACTION_RUN','ACTION_RESET_SERVER','ACTION_PREPARE_INSTALL']:
            self.assertIn(action,dispatch)

    def test_destroy_only_cancels_its_owner_and_delayed_updates_are_owner_gated(self):
        source=(JAVA/'ServerService.kt').read_text()
        destroy=source.split('override fun onDestroy()',1)[1].split('override fun onBind',1)[0]
        self.assertIn('archiveWorkers.cancel(archiveWorker)',destroy)
        self.assertNotIn('archiveWorkers.complete(',destroy)
        self.assertNotIn('setArchiveDownloadProgress(null)',destroy)
        self.assertLess(destroy.index('Thread({'),destroy.index('archiveWorkers.awaitFinished(archiveWorker)'))
        self.assertLess(destroy.index('archiveWorkers.awaitFinished(archiveWorker)'),destroy.index('ManagementServer.releaseService'))
        worker=source.split('private fun runArchiveDownload',1)[1].split('private fun resetServer',1)[0]
        self.assertIn('!destroyed && !cancelled.get() && archiveWorkers.owns(lease)',worker)
        self.assertIn('if (archiveWorkers.mayClearProgress(lease)) Bus.setArchiveDownloadProgress(null)',worker)
        self.assertIn('if (token == operation && !destroyed && archiveLease === lease)',worker)
        self.assertLess(worker.index('archiveWorkers.tryAcquire()'),worker.index('Thread({'))
        self.assertLess(worker.index('.callAttr("run_android"'),worker.index('archiveWorkers.complete(lease)'))

    def test_cancelling_state_visible_in_header_notification_and_all_languages(self):
        self.assertIn('val cancelling: Boolean = false',(JAVA/'ArchiveDownloadCallbacks.kt').read_text())
        for name in ['MainActivity.kt','ServerService.kt']:
            source=(JAVA/name).read_text()
            self.assertIn('archive?.cancelling == true -> getString(R.string.archive_download_cancelling)',source)
        for lang in ['values','values-ko','values-ja']:
            elements=ET.parse(ROOT/'android/app/src/main/res'/lang/'strings.xml').getroot()
            values={e.attrib.get('name'):e.text for e in elements}
            self.assertTrue(values['archive_download_cancelling'])
            self.assertTrue(values['log_archive_draining'])

if __name__=='__main__':unittest.main(verbosity=2)
