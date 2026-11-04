# Japanese content in Global clients

Elichika imports missing JP content into the Global client databases during normal
startup and `rebuild_assets`. Android and desktop use the same native upgrade;
there is no additional Python command or separate manual SQL step.

This integrates the migration and translation data contributed by NaufalFajri in
[PR #57](https://github.com/tagundo/elichika/pull/57). The downloaded reference
webpage and its JavaScript/PHP files are not runtime dependencies.

## Order and existing installations

Both regions first receive their original SQL migrations and the existing lesson
and dictionary upgrades. Missing JP rows are then added to GL before client
manifests and server data are regenerated. This order preserves the original
Git-based SQL migration gate.

Existing GL records and owner-written translations take precedence. A known
Japanese fallback can receive its corresponding translated text. Configured
tables without primary keys, such as lesson drop weights, are left intact.
JP databases are opened read-only by the content import.

Suit titles follow `m_suit.member_m_id` to `m_member.name`, then resolve that
dictionary reference in the selected language. A member ID does not necessarily
match its dictionary key suffix: member 211 references `k.m_dic_member_name_212`
(Mia), while member 212 references `k.m_dic_member_name_211` (Lanzhu). The JP
dictionary and suit references already agree; synthesizing dictionary keys from
member IDs caused the incorrect imported titles. Known generated titles are
corrected through the actual references without replacing owner-written titles.

Package memberships that change receive an updated count and a deterministic
version so previously installed clients can download the added resources. Each
database commits its content and source fingerprint together. Interrupted runs
can resume; repeated runs preserve unchanged files and package versions.

Older/custom installations without the complete JP/GL inputs or initialized
lesson data skip the content import with an explanatory server log. Incompatible
schemas fail before import; failures during import stop manifest generation.
This upgrade does not replay missing historical SQL on a hand-modified database.
See [updating assets](updating_assets.md) for that separate situation.

## What becomes available

The bundled EOS data adds 68 costume entries across five promotional series,
44 R accessories, and one 2D song, *Hajimari wa Kimi no Sora*. The 12 additional
difficulty records include that song's three difficulties and nine daily
variants of existing songs. One additional entry is a selectable home background;
other background records are scene assets. New cards and Liella 3D models are
not added.

The existing All costumes and accessory gift tools can grant the imported items.
Existing accounts are not automatically given ownership. Past missions, shops and
events still need their existing server-side availability and acquisition rules;
copying their client metadata does not reactivate them. Resource packs continue
to use the configured CDN/cache and are not all downloaded by this upgrade.

## Verification

```sh
go test -count=1 ./clientdb/upgrades
python3 tests/run_go_tests.py --assets /path/to/pristine/harasho
```

The normal runtime validator checks JP-to-GL content coverage, package counts and
version tokens, source fingerprints, dictionary coverage, and translated names.
For all 68 imported promotional suits it follows the actual suit-to-member
dictionary references and checks the localized owner in EN, KO and ZH titles.
It is also used by Android build and APK audit jobs. Tests use disposable copies;
they do not modify an installed account or the source asset checkout.
