interface ContentAreaProps {
  activeTab: string;
  children: React.ReactNode;
}

export default function ContentArea({ activeTab, children }: ContentAreaProps) {
  return (
    <div className="ca-container" key={activeTab}>
      {children}
    </div>
  );
}
