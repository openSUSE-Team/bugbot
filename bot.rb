require 'cinch'
require 'open-uri'
require 'nokogiri'
require 'socket'

def bugzilla_title(bnc)
  url = "https://bugzilla.novell.com/show_bug.cgi?id=#{bnc}"
  title = Nokogiri::HTML(open(url)).at("title").text
  title.gsub(/Bug\ [0-9]+.../, '')
end

def process_mail(str)
  return nil unless str.match("X-Bugzilla-Classification: openSUSE") != nil
  if str.match("^X-Bugzilla-Type: changed") && str.match("^X-Bugzilla-Changed-Fields: Status Resolution") && ( str.match("^X-Bugzilla-Status: CLOSED") || str.match("^X-Bugzilla-Status: RESOLVED") )
    data=str.match("^Subject: .Bug ([0-9]+). (.+)")
    bnc=data[1]
    name=data[2]
    guy=str.match("https://bugzilla.novell.com/show_bug.cgi.*\n\n\n(.+) <[^>]*> changed:\n")[1]
    return "Bug number #{bnc} about '#{name}' was closed by #{guy}! Yay!"
  end
  if str.match("^X-Bugzilla-Type: new")
    data=str.match("^Subject: .Bug ([0-9]+). New: (.+)")
    bnc=data[1]
    name=data[2]
    return "We have new bug! It's number is #{bnc} and it is about '#{name}'. Who is up for the challenge?"
  end
  nil
end

class MailListener
  def initialize(bot)
    @bot = bot
  end

  def start
    server = TCPServer.new 2000
    loop do
      Thread.start(server.accept) do |client|
        str = client.read(nil)
        client.close
        notification = process_mail(str)
        @bot.handlers.dispatch(:new_announcement, nil, notification) unless notification == nil
      end
    end
  end
end

class AnnounceMail
  include Cinch::Plugin

  listen_to :new_announcement
  def listen(m, message)
    print "Got notification\n"
    Channel("#opensuse-pizza-hackaton").send message
  end
end

bot = Cinch::Bot.new do
  configure do |c|
    c.server = "irc.freenode.org"
    c.nick = "Furcifer"
    c.channels = ["#opensuse-pizza-hackaton"]
    c.plugins.plugins = [AnnounceMail]
  end

  on :message, /bnc#([0-9]+)/i do |m, bnc|
    title = bugzilla_title(bnc)
    m.reply "bnc##{bnc} is '#{title}' - https://bugzilla.novell.com/show_bug.cgi?id=#{bnc}"
  end
end

Thread.new { MailListener.new(bot).start }

bot.start

