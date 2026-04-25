// utils/transcriptUtils.ts
export const formatTimeFromSeconds = (seconds: number): string => {
  if (seconds < 0) return '0:00';
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, '0')}`;
};

export const getSpeakerColor = (speaker: string): string => {
  if (!speaker || speaker === 'UNKNOWN') return 'bg-gray-100 text-gray-500';
  
  const colors = [
    'bg-blue-100 text-blue-700',
    'bg-green-100 text-green-700',
    'bg-purple-100 text-purple-700',
    'bg-orange-100 text-orange-700',
    'bg-pink-100 text-pink-700',
    'bg-indigo-100 text-indigo-700',
    'bg-teal-100 text-teal-700',
    'bg-rose-100 text-rose-700',
    'bg-amber-100 text-amber-700',
    'bg-cyan-100 text-cyan-700',
  ];
  
  const match = speaker.match(/\d+/);
  const index = match ? parseInt(match[0]) % colors.length : 0;
  return colors[index];
};