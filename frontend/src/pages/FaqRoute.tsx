import { ConcentricRings } from "../components/ConcentricRings";
import { ContactEmail } from "../components/ContactEmail";
import { TopNav } from "../components/TopNav";

type QA = { q: string; a: string };

const SECTIONS: { label: string; items: QA[] }[] = [
  {
    label: "getting in",
    items: [
      {
        q: "do i need an invite?",
        a: "yes. mysterymixclub is invite-only — there's no open signup. someone already in a club can send you a club invite link, or a platform admin can send you a general one.",
      },
      {
        q: "what's the waitlist?",
        a: "if you don't have an invite yet, some pages offer a waitlist join box instead. add your email, and we'll email you when a spot opens up.",
      },
      {
        q: "how do i log in?",
        a: "there are no passwords. enter your email on the login page and we'll send you a sign-in link. click it and you're in. the link is single-use and expires after 15 minutes.",
      },
      {
        q: "it's my first time logging in, what happens?",
        a: "you'll be asked to pick a display name and accept the terms of service and privacy policy. after that you land on your clubs.",
      },
    ],
  },
  {
    label: "clubs",
    items: [
      {
        q: "what's a club?",
        a: "a private group of friends running a series of mystery mixes together, like a season. only invited members can see or join it.",
      },
      {
        q: "how do i join one?",
        a: "click an invite link shared by a member. it doubles as account creation and joining, in one step.",
      },
      {
        q: "can i create my own club?",
        a: "yes, from your clubs page. you'll set the club's name, how many mystery mixes it runs for, how many songs each player can submit, and how many votes each player gets. you can then invite friends with a shareable link.",
      },
    ],
  },
  {
    label: "mystery mixes",
    items: [
      {
        q: "what's a mystery mix?",
        a: "one round of the club: a theme, a window to submit songs that fit it, a window to vote, and a reveal. a club runs through several of these in sequence.",
      },
      {
        q: "what are the stages?",
        a: "pending (no theme set yet) → open for submission → open for voting → closed. one mystery mix is active at a time, and they move forward only.",
      },
      {
        q: "who sets the theme and deadlines?",
        a: "the club's organizer (or co-organizer, if it has one). themes can be anything — literal or poetic.",
      },
      {
        q: "what happens when a mystery mix closes?",
        a: "results are revealed: who submitted what, the vote counts, the winner (or winners, if tied), and the most noted song. if the club has more mystery mixes left, the next one auto-opens once it has a theme.",
      },
    ],
  },
  {
    label: "submitting a song",
    items: [
      {
        q: "how do i submit?",
        a: "search for a song right in the app, or paste a link you already have. both land on the same kind of submission — there's no lesser option. you can add a short note about why you picked it.",
      },
      {
        q: "do i need a spotify or apple music account?",
        a: "no. mysterymixclub itself is the platform — you can search and submit without connecting anything. a streaming account only matters for how you listen afterward.",
      },
      {
        q: "which services can i paste a link from?",
        a: "spotify, youtube, deezer, apple music, and bandcamp.",
      },
      {
        q: "what if my song is only on youtube or bandcamp?",
        a: "it's still accepted, just flagged as youtube-only or bandcamp-only with a direct link, since it can't be matched onto every service's auto-generated playlist.",
      },
      {
        q: "can i change my submission?",
        a: "yes, any time before the submission deadline.",
      },
    ],
  },
  {
    label: "voting & results",
    items: [
      {
        q: "is voting anonymous?",
        a: "yes. while voting is open, songs are shuffled into one playlist with no names attached — nobody can tell who submitted what until the mystery mix closes.",
      },
      {
        q: "can i vote for my own song?",
        a: "no. everything else is fair game, up to your club's vote limit.",
      },
      {
        q: "what's \"most noted\"?",
        a: "a separate recognition from winning: the song that collected the most written notes from other members. it runs alongside the vote-based winner, not instead of it, and can be won by a different song entirely.",
      },
      {
        q: "can i leave notes without voting?",
        a: "yes, notes and votes are independent.",
      },
    ],
  },
  {
    label: "just vibing",
    items: [
      {
        q: "what is just vibing?",
        a: "a non-competitive mode you can turn on for yourself, club-wide or for a single mystery mix. your song still gets submitted, shuffled in, and is fully eligible to win or get most noted — you just don't cast votes.",
      },
      {
        q: "will people know i'm vibing?",
        a: "no. it's invisible to everyone else, during voting and at reveal.",
      },
      {
        q: "do i see the leaderboard if i'm vibing?",
        a: "not the vote counts or leaderboard — you'll still see the winner, most noted, and every submission with its notes.",
      },
    ],
  },
  {
    label: "listening & playlists",
    items: [
      {
        q: "how do i listen to a mystery mix?",
        a: "once voting opens, a shared playlist is available from the mystery mix page.",
      },
      {
        q: "which services get an auto-generated playlist?",
        a: "spotify, apple music, and youtube. set your preferred one from your profile, and it'll be the default link shown to you across the app.",
      },
      {
        q: "what if a song isn't on my preferred service?",
        a: "the playlist will say so rather than just leaving it out silently, and a youtube link is always offered as a fallback.",
      },
    ],
  },
  {
    label: "notifications",
    items: [
      {
        q: "what emails will i get?",
        a: "one when a mystery mix opens for submissions or voting, one when results are ready, a nudge as a deadline approaches, and one when your club wraps up. organizers also get a note if a mystery mix is ready to open but still needs a theme.",
      },
      {
        q: "can i turn them off?",
        a: "yes, every notification email has a one-click unsubscribe link at the bottom. that doesn't affect sign-in emails — you'll always need those to log in.",
      },
    ],
  },
  {
    label: "your account",
    items: [
      {
        q: "can i change my display name or preferred streaming service?",
        a: "yes, both from your profile page, any time.",
      },
      {
        q: "can i download my data?",
        a: "yes, your profile has a \"download my data\" option that exports everything tied to your account.",
      },
      {
        q: "can i delete my account?",
        a: "yes, from your profile. this removes your submissions, votes, notes, and club memberships.",
      },
    ],
  },
  {
    label: "other things to know",
    items: [
      {
        q: "is mysterymixclub free?",
        a: "yes. there's a voluntary tip jar linked on the about page, but nothing is paywalled and there are no ads.",
      },
      {
        q: "does it use ai on my data?",
        a: "no. ai was used to help build the app, but no ai ingests or processes your data as part of using it.",
      },
    ],
  },
];

/**
 * Public FAQ page (MYS-216) — no auth required, linked from the login screen
 * footer and TopNav. Mirrors TermsRoute/PrivacyRoute's layout; TopNav collapses
 * to a login-only nav for signed-out visitors.
 */
export function FaqRoute() {
  return (
    <div className="min-h-screen flex flex-col">
      <TopNav />
      <main className="flex-1 flex flex-col items-center px-4 py-16 sm:px-8">
        <div className="w-full max-w-md">
          {/* Motif — the screen's single Rust use lives in the off-center ring dot. */}
          <ConcentricRings size={72} accent className="mx-auto" />

          <h1 className="mt-8 text-center font-serif text-[34px] leading-tight">faq</h1>
          <p className="mt-2 text-center font-mono text-[11px] font-light text-muted">
            everything from signing in to your first reveal
          </p>

          <div className="mt-10 space-y-10">
            {SECTIONS.map((section) => (
              <section key={section.label}>
                <p className="font-mono text-[9px] uppercase tracking-[0.15em] text-muted">
                  {section.label}
                </p>
                <div className="mt-4 space-y-5">
                  {section.items.map((item) => (
                    <div key={item.q}>
                      <p className="font-mono text-[13px] leading-relaxed text-ink">{item.q}</p>
                      <p className="mt-1 font-mono text-[13px] font-light leading-relaxed text-muted">
                        {item.a}
                      </p>
                    </div>
                  ))}
                </div>
              </section>
            ))}

            <section className="border-t border-border pt-6">
              <p className="font-mono text-[9px] uppercase tracking-[0.15em] text-muted">
                still have questions
              </p>
              <p className="mt-3 font-mono text-[13px] font-light leading-relaxed text-ink">
                <ContactEmail
                  user="info"
                  domain="mysterymixclub.com"
                  label="email us"
                  className="text-sage underline underline-offset-[3px] hover:text-ink"
                />{" "}
                and we'll help you out.
              </p>
            </section>
          </div>
        </div>
      </main>
    </div>
  );
}
