'use client';

/** Inline glossary tooltips: hover/focus/tap the ⓘ next to a technical term
 *  to get a plain-language, equation-free definition — pulled from the
 *  translations so it localizes with the rest of the UI.  Built on Radix
 *  Tooltip for correct keyboard focus, escape-to-close and positioning. */
import * as Tooltip from '@radix-ui/react-tooltip';
import { useTranslation } from 'react-i18next';

export default function Help({ term }: { term: string }) {
  const { t, i18n } = useTranslation();
  const key = `glossary.${term}`;
  const text = i18n.exists(key) ? t(key) : '';
  if (!text) return null;
  return (
    <Tooltip.Provider delayDuration={150}>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>
          <span className="help-tip" tabIndex={0} role="note" aria-label={text}>ⓘ</span>
        </Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content className="help-pop" side="top" align="center"
            sideOffset={6} collisionPadding={12}>
            {text}
            <Tooltip.Arrow className="help-arrow" />
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  );
}
