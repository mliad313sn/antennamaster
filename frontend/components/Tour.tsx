'use client';

/**
 * First-run guided walkthrough (react-joyride).  Explains placing points,
 * choosing a technology, uploading a DXF and reading the coverage heatmap.
 * Loaded only in the browser (joyride touches window), auto-starts once for
 * new users, and is replayable from the header "Take the tour" button.
 * Steps are fully translated.
 */
import { useEffect, useState } from 'react';
import dynamic from 'next/dynamic';
import { useTranslation } from 'react-i18next';
import type { CallBackProps, Step } from 'react-joyride';

const Joyride = dynamic(() => import('react-joyride'), { ssr: false });

const SEEN_KEY = 'am_tour_seen_v1';

export interface TourProps {
  run: boolean;
  onFinish: () => void;
}

export default function Tour({ run, onFinish }: TourProps) {
  const { t } = useTranslation();
  const [steps, setSteps] = useState<Step[]>([]);

  useEffect(() => {
    // Build steps against elements that exist on the planner; joyride skips
    // any target it can't find, so optional panels degrade gracefully.
    const s: Step[] = [
      { target: 'body', placement: 'center',
        title: t('tour.welcome.title'), content: t('tour.welcome.body') },
      { target: '[data-tour="mode"]',
        title: t('tour.simpleMode.title'), content: t('tour.simpleMode.body') },
      { target: '[data-tour="arrange"]',
        title: t('tour.arrange.title'), content: t('tour.arrange.body') },
      { target: '[data-tour="map"]', placement: 'right',
        title: t('tour.place.title'), content: t('tour.place.body') },
      { target: '[data-tour="technology"]',
        title: t('tour.technology.title'), content: t('tour.technology.body') },
      { target: '[data-tour="dxf"]',
        title: t('tour.dxf.title'), content: t('tour.dxf.body') },
      { target: '[data-tour="coverage"]',
        title: t('tour.coverage.title'), content: t('tour.coverage.body') },
      { target: '[data-tour="glossary"]',
        title: t('tour.glossary.title'), content: t('tour.glossary.body') },
    ];
    setSteps(s);
  }, [t]);

  // react-joyride renders into a portal it appends to <body>. Unmounting the
  // component when the tour ends can leave that portal behind, and its
  // full-screen `.react-joyride__overlay` keeps swallowing every pointer
  // event - so a first-time visitor who skipped the tour was left unable to
  // click the map at all. Sweep it once the tour is no longer running.
  // (Found by the browser test, which named the intercepting element.)
  useEffect(() => {
    if (run) return;
    document.getElementById('react-joyride-portal')?.remove();
  }, [run]);

  function handle(data: CallBackProps) {
    const finished = data.status === 'finished' || data.status === 'skipped';
    if (finished) {
      try { localStorage.setItem(SEEN_KEY, '1'); } catch { /* ignore */ }
      onFinish();
    }
  }

  if (!run || steps.length === 0) return null;
  return (
    <Joyride
      steps={steps}
      run={run}
      continuous
      showSkipButton
      showProgress
      disableScrolling
      callback={handle}
      locale={{ skip: t('tour.skip'), back: t('tour.back'),
        next: t('tour.next'), last: t('tour.last') }}
      styles={{
        options: {
          primaryColor: '#2a78d6',
          zIndex: 6000,
          arrowColor: 'var(--surface-1, #fff)',
          backgroundColor: 'var(--surface-1, #fff)',
          textColor: 'var(--ink-primary, #10151f)',
        },
      }}
    />
  );
}

export function tourAlreadySeen(): boolean {
  if (typeof window === 'undefined') return true;
  return localStorage.getItem(SEEN_KEY) === '1';
}
