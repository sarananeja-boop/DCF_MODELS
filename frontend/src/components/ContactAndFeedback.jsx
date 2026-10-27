import React, { useState } from 'react';
import axios from 'axios';
import { toast } from 'react-hot-toast';
import { FaLinkedin } from 'react-icons/fa';
import { FiMail, FiArrowUpRight, FiCheckCircle } from 'react-icons/fi';

export default function ContactAndFeedback({ currentTicker = '' }) {
  const [category, setCategory] = useState('bug');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [message, setMessage] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const myEmail = 'sarandeepaneja@gmail.com';
  const linkedInUrl = 'https://www.linkedin.com/in/sarandeepaneja/';

  const FORMSPREE_ENDPOINT = 'https://formspree.io/f/mzeeeljk';

  const handleSubmit = async (e) => {
    e?.preventDefault();
    const cleanName = name.trim();
    const cleanEmail = email.trim();
    const cleanMessage = message.trim();

    if (!cleanName) {
      toast.error('Please enter your name.');
      return;
    }
    if (!cleanEmail || !cleanEmail.includes('@') || !cleanEmail.includes('.')) {
      toast.error('Please enter a valid email address.');
      return;
    }
    if (!cleanMessage || cleanMessage.length < 3) {
      toast.error('Please enter your feedback before submitting.');
      return;
    }

    setSubmitting(true);
    try {
      // 1. Send directly to Formspree (delivers straight to sarandeepaneja@gmail.com)
      await axios.post(
        FORMSPREE_ENDPOINT,
        {
          name: cleanName,
          email: cleanEmail,
          _replyto: cleanEmail,
          topic: category,
          message: cleanMessage,
          ticker: currentTicker.trim() || undefined,
          _subject: `[ValuationLab Feedback: ${category.toUpperCase()}] from ${cleanName}`,
        },
        {
          headers: {
            Accept: 'application/json',
          },
        }
      );

      // 2. Also keep a local archival copy on backend
      try {
        axios.post('/api/feedback', {
          category,
          message: cleanMessage,
          name: cleanName,
          email: cleanEmail,
          ticker: currentTicker.trim() || null,
        }).catch(() => {});
      } catch (_) {}

      setSubmitted(true);
      toast.success('Feedback sent to sarandeepaneja@gmail.com!');
    } catch (_) {
      // Fallback: If Formspree fails, offer direct mailto link
      const subject = encodeURIComponent(`ValuationLab Feedback (${category}) from ${cleanName}`);
      const body = encodeURIComponent(
        `Category: ${category}\nName: ${cleanName}\nEmail: ${cleanEmail}\n\n${cleanMessage}`
      );
      window.location.href = `mailto:${myEmail}?subject=${subject}&body=${body}`;
      setSubmitted(true);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section id="contact-feedback" className="space-y-10 pt-10 border-t border-[#f4eedf]/10">
      <div>
        <span className="text-sm sm:text-base md:text-lg font-mono uppercase tracking-[0.22em] text-[#e3b23c] block mb-3 font-bold">
          06 · Contact &amp; Feedback
        </span>
        <h2 className="font-display text-3xl sm:text-4xl lg:text-5xl font-bold text-[#f4eedf] tracking-tight">
          Get in Touch &amp; Leave Feedback
        </h2>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-10 lg:gap-16 items-start">
        {/* Left Column: Simple Name, Roadmap & Contact Details (Open Layout, No Boxes) */}
        <div className="space-y-6">
          <div className="space-y-3">
            <span className="text-xs sm:text-sm font-mono uppercase tracking-wider text-[#e3b23c] font-semibold block">
              Contact Me
            </span>
            <h3 className="font-display text-2xl sm:text-3xl font-bold text-[#f4eedf] tracking-tight">
              Sarandeep Aneja
            </h3>
            <p className="text-base sm:text-[16.5px] text-[#d1d7e0] leading-relaxed">
              We are continuously updating and improving this platform, and will keep adding more features and valuation methodologies to make it stronger, more accurate, and more useful over time.
            </p>
            <p className="text-base sm:text-[16.5px] text-[#d1d7e0] leading-relaxed">
              If you spot any errors, data discrepancies, or have suggestions on how the website can be improved, please feel free to reach out directly or leave a note in the feedback form.
            </p>
          </div>

          <div className="pt-2 space-y-4">
            <div className="flex items-center gap-3.5">
              <a
                href={linkedInUrl}
                target="_blank"
                rel="noopener noreferrer"
                aria-label="Sarandeep Aneja LinkedIn"
                className="inline-flex items-center justify-center w-10 h-10 rounded-lg bg-[#0a66c2] hover:bg-[#004182] text-white transition cursor-pointer shrink-0"
              >
                <FaLinkedin className="w-5 h-5" />
              </a>
              <div>
                <span className="text-xs text-[#a6b0c3] block">LinkedIn</span>
                <a
                  href={linkedInUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm sm:text-base font-medium text-[#f4eedf] hover:text-[#e3b23c] inline-flex items-center gap-1 transition"
                >
                  <span>linkedin.com/in/sarandeepaneja</span>
                  <FiArrowUpRight className="w-4 h-4" />
                </a>
              </div>
            </div>

            <div className="flex items-center gap-3.5">
              <a
                href={`mailto:${myEmail}`}
                aria-label="Email Sarandeep Aneja"
                className="inline-flex items-center justify-center w-10 h-10 rounded-lg bg-[#182334] hover:bg-[#223046] text-[#e3b23c] border border-[#f4eedf]/12 transition cursor-pointer shrink-0"
              >
                <FiMail className="w-5 h-5" />
              </a>
              <div>
                <span className="text-xs text-[#a6b0c3] block">Email</span>
                <a
                  href={`mailto:${myEmail}`}
                  className="text-sm sm:text-base font-medium text-[#f4eedf] hover:text-[#e3b23c] transition"
                >
                  {myEmail}
                </a>
              </div>
            </div>
          </div>
        </div>

        {/* Right Column: Leave Feedback Form (Open Layout, Dropdown Topic Selector) */}
        <div className="space-y-5">
          <div className="space-y-2">
            <span className="text-xs sm:text-sm font-mono uppercase tracking-wider text-[#5b8fd9] font-semibold block">
              Leave Feedback
            </span>
            <h3 className="font-display text-2xl sm:text-3xl font-bold text-[#f4eedf] tracking-tight">
              Report an Error or Suggest Improvements
            </h3>
          </div>

          {submitted ? (
            <div className="py-6 space-y-4">
              <div className="flex items-center gap-2.5 text-[#34b38a] font-display font-bold text-lg">
                <FiCheckCircle className="w-5 h-5 shrink-0" />
                <span>Thank you, your feedback has been sent.</span>
              </div>
              <p className="text-sm text-[#d1d7e0] leading-relaxed">
                Your message has been delivered directly to <strong className="text-[#f4eedf]">{myEmail}</strong>. We review all reports as we continue improving the platform.
              </p>
              <div className="pt-2">
                <button
                  type="button"
                  onClick={() => {
                    setMessage('');
                    setSubmitted(false);
                  }}
                  className="px-5 py-2.5 rounded-xl bg-[#182334] hover:bg-[#223046] text-[#f4eedf] border border-[#f4eedf]/12 text-xs font-bold transition cursor-pointer"
                >
                  Send Another Response
                </button>
              </div>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div>
                  <label className="text-xs font-medium text-[#a6b0c3] block mb-1.5">
                    Topic
                  </label>
                  <select
                    value={category}
                    onChange={(e) => setCategory(e.target.value)}
                    className="w-full bg-[#101722] border border-[#f4eedf]/15 focus:border-[#e3b23c] rounded-xl px-3.5 py-2.5 text-xs sm:text-sm text-[#f4eedf] focus:outline-none cursor-pointer transition"
                  >
                    <option value="bug">Report an Error / Bug</option>
                    <option value="feature">Feature / Improvement</option>
                    <option value="model">Valuation Model Feedback</option>
                    <option value="general">General Feedback</option>
                  </select>
                </div>

                <div>
                  <label className="text-xs font-medium text-[#a6b0c3] block mb-1.5">
                    Name
                  </label>
                  <input
                    type="text"
                    required
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Your name"
                    className="w-full bg-[#101722] border border-[#f4eedf]/15 focus:border-[#e3b23c] rounded-xl px-3.5 py-2.5 text-xs sm:text-sm text-[#f4eedf] placeholder-[#a6b0c3]/50 focus:outline-none transition"
                  />
                </div>

                <div>
                  <label className="text-xs font-medium text-[#a6b0c3] block mb-1.5">
                    Email
                  </label>
                  <input
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="Your email"
                    className="w-full bg-[#101722] border border-[#f4eedf]/15 focus:border-[#e3b23c] rounded-xl px-3.5 py-2.5 text-xs sm:text-sm text-[#f4eedf] placeholder-[#a6b0c3]/50 focus:outline-none transition"
                  />
                </div>
              </div>

              <div>
                <label className="text-xs font-medium text-[#a6b0c3] block mb-1.5">
                  Message
                </label>
                <textarea
                  rows={4}
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  placeholder="Write your feedback, report any errors you found, or share how we can improve the website..."
                  required
                  className="w-full bg-[#101722] border border-[#f4eedf]/15 focus:border-[#e3b23c] rounded-xl p-3.5 text-xs sm:text-sm text-[#f4eedf] placeholder-[#a6b0c3]/50 focus:outline-none transition leading-relaxed resize-y"
                />
              </div>

              <div>
                <button
                  type="submit"
                  disabled={submitting || !name.trim() || !email.trim() || !message.trim()}
                  className="px-6 py-3 rounded-xl bg-[#e3b23c] hover:bg-[#ecc052] disabled:opacity-40 text-[#0f141c] font-bold text-xs shadow-md transition cursor-pointer"
                >
                  {submitting ? 'Submitting...' : 'Submit Feedback'}
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </section>
  );
}
