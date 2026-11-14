package sh.edm.s1kiosk.voice

import android.app.Application
import org.junit.After
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import java.nio.file.Files
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** The microphone's thread hands frames on and returns: the model never runs at its priority (#244). */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = Application::class)
class VoiceEngineMicThreadTest {
    private val inModel = CountDownLatch(1)
    private val release = CountDownLatch(1)
    @Volatile private var modelThread: String? = null

    private val slow = object : WakeDetector {
        override fun process(frame: ShortArray): Float {
            modelThread = Thread.currentThread().name
            inModel.countDown()
            release.await(10, TimeUnit.SECONDS)
            return 0f
        }
        override fun close() {}
    }

    private val engine = VoiceEngine(
        RuntimeEnvironment.getApplication(),
        VoiceConfig(modelsDir = Files.createTempDirectory("models").toFile()),
        "hey_jarvis", onActiveWordChanged = {},
    ) { slow }.also { it.start(muted = true) }

    @After fun stop() {
        release.countDown()
        engine.stop()
    }

    private fun loaded() {
        val until = System.currentTimeMillis() + 5_000
        while (true) {
            engine.onMicFrame(ShortArray(1280))
            if (inModel.await(50, TimeUnit.MILLISECONDS)) return
            assertTrue("the model loaded", System.currentTimeMillis() < until)
        }
    }

    @Test
    fun aSlowModelDoesNotHoldUpTheMicrophone() {
        loaded()
        val mic = Thread { repeat(40) { engine.onMicFrame(ShortArray(1280)) } }
        mic.start()
        mic.join(2_000)
        assertFalse("40 frames handed on while the model is busy with one", mic.isAlive)
        assertTrue("the model runs on its own thread, not the microphone's", modelThread == "voice-ww")
    }
}
