'use strict';
// Read-only MediaCodec probe for Redroid: does an H.264/HEVC encoder start and encode one frame
// through flexible-YUV input images (exactly as the FOVMOD 18.7 exporter's makeVideo/feed do),
// and does the AAC encoder accept 16-bit PCM the way its makeAudio/feed do?
// Runs inside an ordinary app process (no game involved); creates and releases its own codecs.

var ENCODE_TIMEOUT_US = 3000000;

function probe(opts) {
  var out = { device: {}, encoders: {}, video: [], audio: [] };
  var Build = Java.use('android.os.Build');
  var Version = Java.use('android.os.Build$VERSION');
  out.device = { release: String(Version.RELEASE.value), sdk: Version.SDK_INT.value, model: String(Build.MODEL.value),
                 hardware: String(Build.HARDWARE.value) };
  var MediaFormat = Java.use('android.media.MediaFormat');
  var MediaCodec = Java.use('android.media.MediaCodec');
  var MediaCodecList = Java.use('android.media.MediaCodecList');
  var BufferInfo = Java.use('android.media.MediaCodec$BufferInfo');
  var infos = MediaCodecList.$new(0).getCodecInfos();

  function encodersFor(type) {
    var found = [];
    for (var i = 0; i < infos.length; i++) {
      var info = infos[i];
      if (!info.isEncoder()) continue;
      var types = info.getSupportedTypes();
      for (var j = 0; j < types.length; j++) {
        if (String(types[j]).toLowerCase() !== type) continue;
        var entry = { name: String(info.getName()) };
        try { entry.canonical = String(info.getCanonicalName()); entry.alias = info.isAlias(); entry.software = info.isSoftwareOnly(); } catch (e) {}
        try {
          var caps = info.getCapabilitiesForType(type);
          var cf = caps.colorFormats.value;
          entry.colorFormats = cf ? Array.prototype.slice.call(cf).map(Number) : [];
        } catch (e) { entry.capsError = String(e); }
        found.push(entry);
      }
    }
    return found;
  }

  function drainOne(codec, result) {
    var info = BufferInfo.$new();
    var deadline = Date.now() + ENCODE_TIMEOUT_US / 1000;
    while (Date.now() < deadline) {
      var o = codec.dequeueOutputBuffer(info, 100000);
      if (o >= 0) {
        var flags = info.flags.value, size = info.size.value;
        codec.releaseOutputBuffer(o, false);
        if ((flags & 2) === 0 && size > 0) { result.encodedBytes = size; return true; }
        if (flags & 4) { result.eosOnly = true; return false; }
      } else if (o === -2) {
        result.outputFormat = String(codec.getOutputFormat());
      }
    }
    result.drainTimeout = true;
    return false;
  }

  function release(codec) {
    if (!codec) return;
    try { codec.stop(); } catch (e) {}
    try { codec.release(); } catch (e) {}
  }

  function video(name, mime, w, h, colorFormat) {
    var r = { name: name, mime: mime, w: w, h: h, colorFormat: colorFormat, stage: 'create' };
    var codec = null;
    try {
      var f = MediaFormat.createVideoFormat(mime, w, h);
      f.setInteger('bitrate', 5000000);
      f.setInteger('frame-rate', 30);
      f.setInteger('i-frame-interval', 2);
      f.setInteger('color-format', colorFormat);
      f.setInteger('color-standard', 1);
      f.setInteger('color-range', 2);
      f.setInteger('color-transfer', 3);
      f.setInteger('max-bframes', 0);
      codec = MediaCodec.createByCodecName(name);
      r.stage = 'configure';
      codec.configure.overload('android.media.MediaFormat', 'android.view.Surface', 'android.media.MediaCrypto', 'int')
        .call(codec, f, null, null, 1);
      r.stage = 'start';
      codec.start();
      r.stage = 'dequeue-input';
      var idx = codec.dequeueInputBuffer(ENCODE_TIMEOUT_US);
      if (idx < 0) throw new Error('no input buffer: ' + idx);
      r.stage = 'input-image';
      var image = codec.getInputImage(idx);
      r.inputImage = image !== null;
      if (image !== null) { r.imageFormat = image.getFormat(); r.planes = image.getPlanes().length; }
      r.stage = 'queue';
      codec.queueInputBuffer(idx, 0, (w * h * 3) / 2, 0, 0);
      var eos = codec.dequeueInputBuffer(ENCODE_TIMEOUT_US);
      if (eos >= 0) codec.queueInputBuffer(eos, 0, 0, 33333, 4);
      r.stage = 'drain';
      r.ok = drainOne(codec, r) && r.inputImage === true;
      r.stage = 'done';
    } catch (e) {
      r.ok = false;
      r.error = String(e).slice(0, 600);
    } finally {
      release(codec);
    }
    return r;
  }

  function audio(name, rate, channels) {
    var r = { name: name, rate: rate, channels: channels, stage: 'create' };
    var codec = null;
    try {
      var f = MediaFormat.createAudioFormat('audio/mp4a-latm', rate, channels);
      f.setInteger('aac-profile', 2);
      f.setInteger('bitrate', 192000);
      f.setInteger('max-input-size', channels * 4096 * 2);
      codec = MediaCodec.createByCodecName(name);
      r.stage = 'configure';
      codec.configure.overload('android.media.MediaFormat', 'android.view.Surface', 'android.media.MediaCrypto', 'int')
        .call(codec, f, null, null, 1);
      r.stage = 'start';
      codec.start();
      r.stage = 'dequeue-input';
      var idx = codec.dequeueInputBuffer(ENCODE_TIMEOUT_US);
      if (idx < 0) throw new Error('no input buffer: ' + idx);
      var buffer = codec.getInputBuffer(idx);
      if (buffer === null) throw new Error('Missing AAC input buffer');
      buffer.clear();
      r.capacity = buffer.capacity();
      r.remaining = buffer.remaining();
      var frame = channels * 2;
      var n = Math.min(4096 * frame, Math.floor(buffer.remaining() / frame) * frame);
      r.pcmBytes = n;
      if (n === 0) throw new Error('AAC buffer cannot hold one PCM frame');
      var zeros = [];
      for (var i = 0; i < n; i++) zeros.push(0);
      buffer.put(Java.array('byte', zeros));
      r.stage = 'queue';
      codec.queueInputBuffer(idx, 0, n, 0, 0);
      var eos = codec.dequeueInputBuffer(ENCODE_TIMEOUT_US);
      if (eos >= 0) codec.queueInputBuffer(eos, 0, 0, Math.floor((4096 * 1000000) / rate), 4);
      r.stage = 'drain';
      r.ok = drainOne(codec, r);
      r.stage = 'done';
    } catch (e) {
      r.ok = false;
      r.error = String(e).slice(0, 600);
    } finally {
      release(codec);
    }
    return r;
  }

  ['video/avc', 'video/hevc', 'audio/mp4a-latm'].forEach(function (type) { out.encoders[type] = encodersFor(type); });
  ['video/avc', 'video/hevc'].forEach(function (mime) {
    out.encoders[mime].forEach(function (e) {
      opts.sizes.forEach(function (size) {
        opts.colorFormats.forEach(function (cf) { out.video.push(video(e.name, mime, size[0], size[1], cf)); });
      });
    });
  });
  out.encoders['audio/mp4a-latm'].forEach(function (e) {
    opts.audio.forEach(function (a) { out.audio.push(audio(e.name, a[0], a[1])); });
  });
  return out;
}

rpc.exports = {
  run: function (opts) {
    return new Promise(function (resolve, reject) {
      Java.perform(function () {
        try { resolve(probe(opts)); } catch (e) { reject(e); }
      });
    });
  }
};
