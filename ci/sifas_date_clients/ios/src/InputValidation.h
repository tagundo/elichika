#ifndef SIFAS_INPUT_VALIDATION_H
#define SIFAS_INPUT_VALIDATION_H
/* Small, deterministic lexical checks; URL authority is checked by NSURL too. */
static int SIFASMatch(const char **cursor, const char *literal) {
    const char *p = *cursor;
    while (*literal) if (*p++ != *literal++) return 0;
    *cursor = p;
    return 1;
}
static int SIFASBase64(const char **cursor) {
    const unsigned char *p = (const unsigned char *)*cursor;
    unsigned int count = 0, padding = 0;
    while (*p && *p != '<') {
        unsigned char c = *p++;
        if (c == '=') { if (++padding > 2) return 0; }
        else if (padding || !((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
                              (c >= '0' && c <= '9') || c == '+' || c == '/')) return 0;
        count++;
    }
    if (count < 4 || count % 4 || padding == count) return 0;
    *cursor = (const char *)p;
    return 1;
}
static int SIFASValidPublicKey(const char *text) {
    if (!text) return 0;
    const char *p = text;
    return SIFASMatch(&p,"<RSAKeyValue><Modulus>") && SIFASBase64(&p) &&
           SIFASMatch(&p,"</Modulus><Exponent>") && SIFASBase64(&p) &&
           SIFASMatch(&p,"</Exponent></RSAKeyValue>") && !*p;
}
static int SIFASValidURLCharacters(const char *text) {
    if (!text || !*text) return 0;
    const char *p = text;
    if (!SIFASMatch(&p,"http://")) { p = text; if (!SIFASMatch(&p,"https://")) return 0; }
    if (!*p) return 0;
    for (const unsigned char *c = (const unsigned char *)text; *c; c++)
        if (*c <= 32 || *c == 127 || *c == '\\') return 0;
    return 1;
}
#endif
